"""Attendance rules: what is scheduled, what is pending, who may edit, and saving records."""
import datetime
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone

from academics.models import Holiday, SchoolClass, is_holiday
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
    """One scheduled period of one class on one date, with its attendance (if entered)."""
    school_class: SchoolClass
    date: datetime.date
    period_no: int
    entry: TimetableEntry
    session: AttendanceSession | None

    @property
    def completed(self):
        return self.session is not None

    @property
    def status(self):
        return "completed" if self.completed else "pending"

    @property
    def subject(self):
        return self.session.subject if self.session else self.entry.subject

    @property
    def faculty(self):
        return self.session.taken_by if self.session else self.entry.faculty


class ScheduleIndex:
    """Loads timetables, holidays and attendance for a date range once, then answers questions in memory."""

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
        sessions = AttendanceSession.objects.filter(date__range=(start, end)).select_related("subject", "taken_by")
        self.sessions = {(s.school_class_id, s.date, s.period_no): s for s in sessions}

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

    def slots(self, date, class_id=None, faculty_id=None):
        out = []
        for c in self.classes:
            if class_id and c.pk != class_id:
                continue
            if self.holiday_reason(date, c.pk):
                continue
            for e in (self._version(c.pk, date) or {}).get(date.weekday(), []):
                if faculty_id and e.faculty_id != faculty_id:
                    continue
                out.append(Slot(c, date, e.period_no, e, self.sessions.get((c.pk, date, e.period_no))))
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


def save_attendance(*, school_class, date, period_no, entry, user, absent_ids, topic, remarks=""):
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
    taken_by = entry.faculty if user.is_admin_role else user
    try:
        with transaction.atomic():
            session = AttendanceSession.objects.create(
                school_class=school_class, date=date, period_no=period_no, subject=entry.subject,
                taken_by=taken_by, scheduled_subject=entry.subject, scheduled_faculty=entry.faculty,
                topic=topic, remarks=(remarks or "").strip())
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
