"""Attendance rules: what is scheduled, what is pending, who may edit, and saving records."""
import datetime
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone

from academics.models import Holiday, SchoolClass, forenoon_last_period, is_holiday
from leaves.models import Adjustment, LeaveDay, LeaveRequest
from leaves.periods import covered_periods
from timetable.models import Timetable, TimetableEntry
from timetable.services import timetable_in_force

from .models import AttendanceAudit, AttendanceRecord, AttendanceSession


def today():
    return timezone.localdate()


class AttendanceError(Exception):
    """A rule was broken; the message is safe to show to the user."""


class DuplicateAttendance(AttendanceError):
    pass


# ---------------------------------------------------------------- schedule

@dataclass
class Slot:
    """One scheduled period of one class on one date, with its attendance (if entered).

    `adjustment` is the substitution in force for this period (leave or return), if any.
    `on_leave` is True when the timetable faculty is on approved leave and nobody has been fixed yet."""
    school_class: SchoolClass
    date: datetime.date
    period_no: int
    entry: TimetableEntry
    session: AttendanceSession | None
    adjustment: Adjustment | None = None
    on_leave: bool = False

    @property
    def completed(self):
        return self.session is not None

    @property
    def unadjusted(self):
        return self.on_leave and self.adjustment is None and self.session is None

    @property
    def status(self):
        return "completed" if self.completed else ("unadjusted" if self.unadjusted else "pending")

    @property
    def subject(self):
        if self.session:
            return self.session.subject
        return self.adjustment.subject_taught if self.adjustment else self.entry.subject

    @property
    def faculty(self):
        if self.session:
            return self.session.taken_by
        return self.adjustment.substitute if self.adjustment else self.entry.faculty

    @property
    def adjusted_for(self):
        """The faculty member whose period this is, when someone else is taking it."""
        adj = self.session.adjustment if self.session and self.session.adjustment_id else self.adjustment
        return adj.original_faculty if adj else None

    @property
    def is_adjusted(self):
        return self.adjusted_for is not None


class ScheduleIndex:
    """Loads timetables, holidays, leave, adjustments and attendance for a date range once,
    then answers questions in memory."""

    def __init__(self, start, end):
        self.classes = list(SchoolClass.objects.all())
        entries = Prefetch("entries", queryset=TimetableEntry.objects.select_related("subject", "faculty"))
        self.versions = {}
        for tt in Timetable.objects.prefetch_related(entries).order_by("effective_from"):
            by_day = {}
            for e in tt.entries.all():
                by_day.setdefault(e.day, []).append(e)
            self.versions.setdefault(tt.school_class_id, []).append((tt.effective_from, by_day))
        self.holidays = list(Holiday.objects.filter(to_date__gte=start, from_date__lte=end))
        sessions = (AttendanceSession.objects.filter(date__range=(start, end))
                    .select_related("subject", "taken_by", "adjustment__original_faculty"))
        self.sessions = {(s.school_class_id, s.date, s.period_no): s for s in sessions}
        # substitutions in force: accepted, and the leave itself approved
        adjs = (Adjustment.objects.filter(date__range=(start, end), status=Adjustment.ACCEPTED,
                                          leave_request__status=LeaveRequest.APPROVED)
                .select_related("substitute", "original_faculty", "subject_taught"))
        self.adjustments = {(a.school_class_id, a.date, a.period_no): a for a in adjs}
        # who is on approved leave, and for which periods
        fl = forenoon_last_period()
        self.leave_cover = {}
        days = LeaveDay.objects.filter(date__range=(start, end), request__status=LeaveRequest.APPROVED
                                       ).select_related("request")
        for d in days:
            cover = covered_periods(d.request.scope, d.request.periods, fl)
            self.leave_cover.setdefault((d.request.faculty_id, d.date), set()).update(cover)

    def holiday_reason(self, date, class_id):
        if date.weekday() == 6:
            return "Sunday"
        for h in self.holidays:
            if h.from_date <= date <= h.to_date and h.school_class_id in (None, class_id):
                return h.reason
        return None

    def _version(self, class_id, date):
        found = None
        for eff, by_day in self.versions.get(class_id, []):
            if eff <= date:
                found = by_day
            else:
                break
        return found

    def entries_for(self, date, class_id):
        """Raw timetable entries for a class on a date (ignores holidays, leave and attendance)."""
        return (self._version(class_id, date) or {}).get(date.weekday(), [])

    def slots(self, date, class_id=None, faculty_id=None):
        """Periods of the day. With `faculty_id`, only periods that faculty is responsible for: their own,
        unless the period was given to a substitute, plus periods they are substituting."""
        out = []
        for c in self.classes:
            if class_id and c.pk != class_id:
                continue
            if self.holiday_reason(date, c.pk):
                continue
            for e in self.entries_for(date, c.pk):
                key = (c.pk, date, e.period_no)
                adj = self.adjustments.get(key)
                on_leave = e.period_no in self.leave_cover.get((e.faculty_id, date), ())
                slot = Slot(c, date, e.period_no, e, self.sessions.get(key), adj, on_leave)
                if faculty_id and (slot.faculty.pk != faculty_id or slot.unadjusted):
                    continue
                out.append(slot)
        out.sort(key=lambda s: (s.period_no, s.school_class.name))
        return out


def faculty_day_and_pending(user, on=None):
    """(today's slots, pending slots from the lookback window up to and including today, oldest first)."""
    on = on or today()
    start = on - datetime.timedelta(days=settings.PENDING_LOOKBACK_DAYS)
    index = ScheduleIndex(start, on)
    todays = index.slots(on, faculty_id=user.pk)
    pending = []
    d = start
    while d <= on:
        pending.extend(s for s in index.slots(d, faculty_id=user.pk) if not s.completed)
        d += datetime.timedelta(days=1)
    return todays, pending


def find_entry(school_class, date, period_no):
    """The timetable entry scheduled for this class/date/period under the version in force, or None."""
    tt = timetable_in_force(school_class, date)
    if not tt:
        return None
    return (tt.entries.select_related("subject", "faculty")
            .filter(day=date.weekday(), period_no=period_no).first())


def find_adjustment(school_class, date, period_no):
    """The substitution in force for this period, or None."""
    return (Adjustment.objects.filter(school_class=school_class, date=date, period_no=period_no,
                                      status=Adjustment.ACCEPTED, leave_request__status=LeaveRequest.APPROVED)
            .select_related("substitute", "original_faculty", "subject_taught").first())


def is_on_leave(faculty_id, date, period_no):
    """True if the faculty has approved leave covering this period."""
    fl = forenoon_last_period()
    for d in LeaveDay.objects.filter(date=date, request__faculty_id=faculty_id,
                                     request__status=LeaveRequest.APPROVED).select_related("request"):
        if period_no in covered_periods(d.request.scope, d.request.periods, fl):
            return True
    return False


def responsible_faculty_id(entry, adjustment, date):
    """Who is meant to take this period: the substitute if there is one, else the timetable faculty
    (None while that faculty is on leave and nobody has been fixed)."""
    if adjustment:
        return adjustment.substitute_id
    if is_on_leave(entry.faculty_id, date, entry.period_no):
        return None
    return entry.faculty_id


# ---------------------------------------------------------------- permissions

def can_view_session(user, session):
    if user.is_admin_role:
        return True
    allotment = getattr(session.subject, "allotment", None)
    return session.taken_by_id == user.pk or (allotment is not None and allotment.faculty_id == user.pk)


def can_edit_session(user, session, on=None):
    """Admin: always. Faculty: only their own entry, and only on the day of the class or the day it was entered,
    unless the admin has unlocked it."""
    if user.is_admin_role:
        return True
    if session.taken_by_id != user.pk:
        return False
    if session.unlocked:
        return True
    on = on or today()
    entered_on = timezone.localtime(session.created_at).date()
    return on == session.date or on == entered_on


def is_locked_for_faculty(session, on=None):
    on = on or today()
    return not (session.unlocked or on == session.date or on == timezone.localtime(session.created_at).date())


# ---------------------------------------------------------------- saving

def _clean_topic(topic):
    topic = (topic or "").strip()
    if not topic:
        raise AttendanceError("The topic covered in this period is required.")
    return topic


def save_attendance(*, school_class, date, period_no, entry, user, absent_ids, topic, remarks="", adjustment=None):
    """Create the attendance for a period. Everyone is present except `absent_ids`."""
    topic = _clean_topic(topic)
    if date > today():
        raise AttendanceError("Attendance cannot be entered for a future date.")
    if is_holiday(date, school_class):
        raise AttendanceError("That date is a holiday.")
    students = list(school_class.students.all())
    if not students:
        raise AttendanceError("This class has no students yet.")
    absent = set(absent_ids) & {s.pk for s in students}
    # Counted under the subject actually taught and credited to whoever took the period.
    subject = adjustment.subject_taught if adjustment else entry.subject
    if adjustment:
        taken_by = adjustment.substitute
    else:
        taken_by = entry.faculty if user.is_admin_role else user
    try:
        with transaction.atomic():
            session = AttendanceSession.objects.create(
                school_class=school_class, date=date, period_no=period_no, subject=subject,
                taken_by=taken_by, scheduled_subject=entry.subject, scheduled_faculty=entry.faculty,
                adjustment=adjustment, topic=topic, remarks=(remarks or "").strip())
            AttendanceRecord.objects.bulk_create(
                [AttendanceRecord(session=session, student=s, present=s.pk not in absent) for s in students])
    except IntegrityError:
        raise DuplicateAttendance("Attendance for this class, date and period has already been entered.")
    return session


def update_attendance(session, *, user, absent_ids, topic, remarks=""):
    if not can_edit_session(user, session):
        raise PermissionDenied
    topic = _clean_topic(topic)
    students = list(session.school_class.students.all())
    absent = set(absent_ids) & {s.pk for s in students}
    with transaction.atomic():
        existing = {r.student_id: r for r in session.records.all()}
        old_absent = {sid for sid, r in existing.items() if not r.present}
        new_records, changed = [], []
        for s in students:
            present = s.pk not in absent
            r = existing.get(s.pk)
            if r is None:
                new_records.append(AttendanceRecord(session=session, student=s, present=present))
            elif r.present != present:
                r.present = present
                changed.append(r)
        AttendanceRecord.objects.bulk_update(changed, ["present"])
        AttendanceRecord.objects.bulk_create(new_records)
        roll = {s.pk: s.roll_no for s in students}
        notes = []
        if topic != session.topic:
            notes.append(f"Topic: '{session.topic}' -> '{topic}'")
        if (remarks or "").strip() != session.remarks:
            notes.append("Remarks changed")
        now_absent = {sid for sid in absent}
        if now_absent != old_absent:
            added = sorted(roll.get(i, str(i)) for i in now_absent - old_absent)
            removed = sorted(roll.get(i, str(i)) for i in old_absent - now_absent)
            notes.append("Absent: " + ", ".join([f"+{r}" for r in added] + [f"-{r}" for r in removed]))
        session.topic = topic
        session.remarks = (remarks or "").strip()
        if not user.is_admin_role:
            session.unlocked = False   # an admin unlock lasts until the faculty re-saves
        session.save()
        if notes:
            AttendanceAudit.objects.create(session=session, user=user, summary="; ".join(notes))
    return session


def set_unlocked(session, unlocked):
    session.unlocked = unlocked
    session.save(update_fields=["unlocked", "updated_at"])


def session_counts(session):
    recs = list(session.records.all())
    absent = sum(1 for r in recs if not r.present)
    return len(recs) - absent, absent
