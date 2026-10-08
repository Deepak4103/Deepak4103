"""Leave and workload-adjustment rules: eligibility, requests, consent, approval, balances."""
import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from academics.models import SchoolClass, Subject, forenoon_last_period, is_holiday
from accounts.models import User
from attendance.models import AttendanceSession
from attendance.services import ScheduleIndex, today
from timetable.models import TimetableEntry
from timetable.services import timetable_in_force

from .models import Adjustment, LeaveDay, LeaveRequest, LeaveType, Notification
from .periods import FULL, PERIODS, covered_periods, day_value, parse_periods

LIVE_ADJ = (Adjustment.UNASSIGNED, Adjustment.PENDING, Adjustment.ACCEPTED, Adjustment.DECLINED)
HOLDING_SLOT = (Adjustment.PENDING, Adjustment.ACCEPTED)     # a substitute with these is committed to that period


class LeaveError(Exception):
    """A rule was broken; the message is safe to show to the user."""


def notify(user, text, url=""):
    if user is not None:
        Notification.objects.create(user=user, text=text[:300], url=url)


def notify_admins(text, url=""):
    for a in User.objects.filter(role=User.ADMIN, is_active=True):
        notify(a, text, url)


# ------------------------------------------------------------------ eligibility

class DayContext:
    """Everything needed to decide who is free on one date (loaded once, reused for every period)."""

    def __init__(self, date):
        self.date = date
        fl = forenoon_last_period()
        self.busy = set()                       # (faculty_id, period_no) teaching their own timetable
        self.teaches_class = {}                 # class_id -> faculty ids (allotment or timetable)
        for c in SchoolClass.objects.all():
            tt = timetable_in_force(c, date)
            ids = set(c.subjects.filter(allotment__isnull=False).values_list("allotment__faculty_id", flat=True))
            if tt:
                for e in tt.entries.all():
                    ids.add(e.faculty_id)
                    if e.day == date.weekday():
                        self.busy.add((e.faculty_id, e.period_no))
            self.teaches_class[c.pk] = ids
        self.leave = {}                         # faculty_id -> periods they are on leave
        for d in LeaveDay.objects.filter(date=date, request__status__in=LeaveRequest.SUBMITTED
                                         ).select_related("request"):
            self.leave.setdefault(d.request.faculty_id, set()).update(
                covered_periods(d.request.scope, d.request.periods, fl))
        self.committed = {}                     # (faculty_id, period_no) -> adjustment ids they already hold
        for a in Adjustment.objects.filter(date=date, status__in=HOLDING_SLOT, substitute__isnull=False):
            self.committed.setdefault((a.substitute_id, a.period_no), set()).add(a.pk)
        self.subject_teachers = {}              # subject id -> faculty teaching a same-code/name subject

    def teachers_of_same_subject(self, subject):
        if subject.pk not in self.subject_teachers:
            same = Subject.objects.filter(Q(code__iexact=subject.code) | Q(name__iexact=subject.name))
            ids = set(same.filter(allotment__isnull=False).values_list("allotment__faculty_id", flat=True))
            ids |= set(TimetableEntry.objects.filter(subject__in=same).values_list("faculty_id", flat=True))
            self.subject_teachers[subject.pk] = ids
        return self.subject_teachers[subject.pk]


def eligible_faculty(school_class, subject, date, period_no, *, original_faculty, ctx=None, ignore_adjustment_id=None):
    """Faculty who may substitute for this period.

    Eligible = active faculty (not the person being replaced) who
      - teach any subject to this same class, or teach the same subject to another class/section; and
      - are free in this period per the timetable; and
      - are not on leave themselves; and
      - are not already committed to another substitution in this period.
    """
    ctx = ctx or DayContext(date)
    related = ctx.teaches_class.get(school_class.pk, set()) | ctx.teachers_of_same_subject(subject)
    out = []
    for f in User.objects.filter(role=User.FACULTY, is_active=True, pk__in=related).exclude(pk=original_faculty.pk):
        if (f.pk, period_no) in ctx.busy:
            continue
        if period_no in ctx.leave.get(f.pk, ()):
            continue
        holding = ctx.committed.get((f.pk, period_no), set()) - {ignore_adjustment_id}
        if holding:
            continue
        out.append(f)
    return out


# ------------------------------------------------------------------ leave requests

def _working_dates(from_date, to_date):
    d = from_date
    while d <= to_date:
        if not is_holiday(d, None):           # Sundays and college-wide holidays are not leave days
            yield d
        d += datetime.timedelta(days=1)


def _overlap_check(faculty, dates, scope, periods, exclude_id=None):
    fl = forenoon_last_period()
    mine = covered_periods(scope, periods, fl)
    existing = LeaveDay.objects.filter(request__faculty=faculty, date__in=dates,
                                       request__status__in=LeaveRequest.SUBMITTED + (LeaveRequest.DRAFT,)
                                       ).select_related("request")
    for d in existing:
        if d.request_id == exclude_id:
            continue
        if mine & covered_periods(d.request.scope, d.request.periods, fl):
            raise LeaveError(f"{faculty.full_name} already has leave on {d.date:%d %b %Y} that overlaps this request.")


@transaction.atomic
def create_leave_request(*, faculty, leave_type, from_date, to_date, scope, periods="", reason="", created_by):
    """Create a leave request with one adjustment row for every affected period (holidays skipped).

    A request entered by an admin is approved straight away (the admin is the approver); one applied for by
    the faculty starts as a draft until every period has a substitute and subject."""
    if to_date < from_date:
        raise LeaveError("The end date cannot be before the start date.")
    if scope == PERIODS and not parse_periods(periods):
        raise LeaveError("Choose at least one period.")
    if created_by.is_faculty_role and from_date < today():
        raise LeaveError("Leave cannot be applied for a past date. Ask the admin to enter it.")
    dates = list(_working_dates(from_date, to_date))
    if not dates:
        raise LeaveError("Those dates are all holidays or Sundays, so no leave is needed.")
    _overlap_check(faculty, dates, scope, periods)
    admin_entry = created_by.is_admin_role
    req = LeaveRequest.objects.create(
        faculty=faculty, leave_type=leave_type, from_date=from_date, to_date=to_date, scope=scope,
        periods=",".join(str(p) for p in sorted(parse_periods(periods))) if scope == PERIODS else "",
        reason=reason, created_by=created_by,
        status=LeaveRequest.APPROVED if admin_entry else LeaveRequest.DRAFT,
        decided_by=created_by if admin_entry else None, decided_at=timezone.now() if admin_entry else None)
    LeaveDay.objects.bulk_create([LeaveDay(request=req, date=d, days_value=day_value(scope)) for d in dates])
    build_adjustment_rows(req)
    return req


def build_adjustment_rows(req):
    """One empty adjustment per period of the faculty that falls in the leave. Periods whose attendance
    was already taken are skipped, as is any class that has a holiday that day."""
    fl = forenoon_last_period()
    cover = covered_periods(req.scope, req.periods, fl)
    first, last = req.days.first().date, req.days.last().date
    index = ScheduleIndex(first, last)
    taken_slots = set(Adjustment.objects.filter(date__range=(first, last)).exclude(status=Adjustment.CANCELLED)
                      .values_list("school_class_id", "date", "period_no"))
    rows = []
    for day in req.days.all():
        for c in index.classes:
            if index.holiday_reason(day.date, c.pk):
                continue
            for e in index.entries_for(day.date, c.pk):
                if e.faculty_id != req.faculty_id or e.period_no not in cover:
                    continue
                if (c.pk, day.date, e.period_no) in index.sessions or (c.pk, day.date, e.period_no) in taken_slots:
                    continue
                rows.append(Adjustment(
                    leave_request=req, kind=Adjustment.LEAVE, school_class=c, date=day.date, period_no=e.period_no,
                    original_faculty=req.faculty, original_subject=e.subject))
    Adjustment.objects.bulk_create(rows)


def leave_adjustments(req):
    return req.adjustments.filter(kind=Adjustment.LEAVE).exclude(status=Adjustment.CANCELLED)


def refresh_status(req):
    """After any change: all leave periods accepted -> waiting for admin; otherwise -> waiting for substitutes."""
    if req.status not in (LeaveRequest.AWAITING_CONSENT, LeaveRequest.AWAITING_ADMIN):
        return
    all_ok = all(a.status == Adjustment.ACCEPTED for a in leave_adjustments(req))
    new = LeaveRequest.AWAITING_ADMIN if all_ok else LeaveRequest.AWAITING_CONSENT
    if new != req.status:
        req.status = new
        req.save(update_fields=["status"])
        if new == LeaveRequest.AWAITING_ADMIN:
            notify_admins(f"{req.faculty.full_name}'s leave is ready for approval.", f"/leaves/{req.pk}/")


def _has_attendance(adj):
    return AttendanceSession.objects.filter(adjustment=adj).exists() or AttendanceSession.objects.filter(
        school_class=adj.school_class, date=adj.date, period_no=adj.period_no).exists()


def _label(adj):
    return f"{adj.school_class.name} P{adj.period_no} on {adj.date:%a %d %b}"


@transaction.atomic
def set_adjustment(adj, *, user, substitute, same_subject, subject=None, ctx_cache=None):
    """Choose (or change) the substitute and subject for one period.

    Faculty changes need the substitute's consent; admin changes are accepted immediately and the substitute is
    simply notified."""
    adj.refresh_from_db()
    req = LeaveRequest.objects.get(pk=adj.leave_request_id)
    if req.status in (LeaveRequest.REJECTED, LeaveRequest.CANCELLED):
        raise LeaveError("This leave is closed.")
    if adj.kind == Adjustment.LEAVE and user.is_faculty_role and (
            req.faculty_id != user.pk or req.status == LeaveRequest.APPROVED):
        raise LeaveError("You cannot change adjustments on an approved leave. Please ask the admin.")
    if _has_attendance(adj):
        raise LeaveError(f"Attendance was already entered for {_label(adj)}; edit that attendance instead.")
    if substitute is None:
        raise LeaveError("Choose a substitute.")
    if same_subject:
        taught = adj.original_subject
    else:
        if subject is None or subject.school_class_id != adj.school_class_id:
            raise LeaveError("Choose the subject to be taught from this class's subjects.")
        if subject.pk == adj.original_subject_id:
            raise LeaveError("That is the same subject; choose 'Same subject' instead.")
        taught = subject
    ctx = (ctx_cache or {}).get(adj.date) or DayContext(adj.date)
    if ctx_cache is not None:
        ctx_cache[adj.date] = ctx
    ok = eligible_faculty(adj.school_class, adj.original_subject, adj.date, adj.period_no,
                          original_faculty=adj.original_faculty, ctx=ctx, ignore_adjustment_id=adj.pk)
    if adj.kind == Adjustment.RETURN and substitute.pk != req.faculty_id:
        ok = []                             # a return is always taken by the applicant
    if substitute.pk not in {f.pk for f in ok}:
        raise LeaveError(f"{substitute.full_name} cannot take {_label(adj)}: not eligible or not free then.")

    previous = adj.substitute
    unchanged = (previous and previous.pk == substitute.pk and adj.subject_taught_id == taught.pk)
    adj.substitute, adj.subject_taught = substitute, taught
    adj.made_by, adj.made_by_role = user, user.role
    if user.is_admin_role:
        adj.status, adj.consent_required = Adjustment.ACCEPTED, False
    elif req.status == LeaveRequest.DRAFT:
        adj.status, adj.consent_required = Adjustment.UNASSIGNED, True   # becomes PENDING when submitted
    elif not (unchanged and adj.status in (Adjustment.PENDING, Adjustment.ACCEPTED)):
        adj.status, adj.consent_required = Adjustment.PENDING, True
    adj.save()
    if previous and previous.pk != substitute.pk and adj.kind == Adjustment.LEAVE and not unchanged:
        notify(previous, f"You are no longer asked to take {_label(adj)}.", "/faculty-home/")
    if not unchanged:
        if user.is_admin_role:
            notify(substitute, f"The admin has assigned you {_label(adj)} ({adj.subject_taught.name})"
                               f" for {adj.original_faculty.full_name}.", "/faculty-home/")
        elif adj.status == Adjustment.PENDING:
            if adj.kind == Adjustment.RETURN:
                notify(adj.original_faculty, f"{req.faculty.full_name} offers to take your {_label(adj)} "
                       f"({adj.subject_taught.name}) in exchange for your cover. Please accept or decline.",
                       "/faculty-home/")
            else:
                notify(substitute, f"{req.faculty.full_name} asks you to take {_label(adj)} "
                       f"({adj.subject_taught.name}). Please accept or decline.", "/faculty-home/")
    refresh_status(req)
    return adj


@transaction.atomic
def clear_adjustment(adj, *, user):
    """Admin: remove the substitute for a period. A leave period goes back to 'no substitute yet'."""
    if not user.is_admin_role:
        raise LeaveError("Only the admin can cancel an adjustment.")
    adj.refresh_from_db()
    if _has_attendance(adj):
        raise LeaveError("Attendance was already entered for this period; edit that attendance instead.")
    old = adj.substitute
    if adj.kind == Adjustment.RETURN:
        adj.status = Adjustment.CANCELLED
    else:
        adj.substitute, adj.subject_taught, adj.status = None, None, Adjustment.UNASSIGNED
        adj.consent_required = True
    adj.made_by, adj.made_by_role = user, user.role
    adj.save()
    notify(old, f"The admin cancelled your adjustment for {_label(adj)}.", "/faculty-home/")
    refresh_status(adj.leave_request)


@transaction.atomic
def submit_request(req, *, user):
    """Faculty submits: every period must have a substitute and a subject."""
    req.refresh_from_db()
    if req.faculty_id != user.pk or req.status != LeaveRequest.DRAFT:
        raise LeaveError("This request cannot be submitted.")
    adjs = list(leave_adjustments(req).select_related("school_class"))
    missing = [a for a in adjs if not a.complete]
    if missing:
        raise LeaveError("Every period needs a substitute and a subject before you can submit. Missing: "
                         + ", ".join(_label(a) for a in missing))
    req.status = LeaveRequest.AWAITING_CONSENT
    req.save(update_fields=["status"])
    for a in adjs:
        if a.status != Adjustment.ACCEPTED:
            a.status = Adjustment.PENDING
            a.save(update_fields=["status", "updated_at"])
            notify(a.substitute, f"{req.faculty.full_name} asks you to take {_label(a)} "
                                 f"({a.subject_taught.name}). Please accept or decline.", "/faculty-home/")
    refresh_status(req)


@transaction.atomic
def respond(adj, *, user, accept):
    """The person asked (substitute for a leave period; the covering colleague for a return) accepts or declines."""
    adj.refresh_from_db()
    if adj.status != Adjustment.PENDING or adj.responder_id != user.pk:
        raise LeaveError("This request is no longer waiting for your answer.")
    req = LeaveRequest.objects.select_related("faculty").get(pk=adj.leave_request_id)
    if req.status in (LeaveRequest.REJECTED, LeaveRequest.CANCELLED):
        raise LeaveError("This leave is closed.")
    if accept:
        ctx = DayContext(adj.date)
        ok = eligible_faculty(adj.school_class, adj.original_subject, adj.date, adj.period_no,
                              original_faculty=adj.original_faculty, ctx=ctx, ignore_adjustment_id=adj.pk)
        if adj.substitute_id not in {f.pk for f in ok}:
            raise LeaveError("This period clashes with something else you now have, so it cannot be accepted.")
        adj.status = Adjustment.ACCEPTED
        notify(req.faculty, f"{user.full_name} accepted {_label(adj)}.", f"/leaves/{req.pk}/")
    else:
        adj.status = Adjustment.DECLINED
        notify(req.faculty, f"{user.full_name} declined {_label(adj)}. Please choose someone else.",
               f"/leaves/{req.pk}/")
    adj.save(update_fields=["status", "updated_at"])
    refresh_status(req)


def _close_adjustments(req):
    req.adjustments.exclude(status=Adjustment.CANCELLED).filter(sessions__isnull=True).update(
        status=Adjustment.CANCELLED)


@transaction.atomic
def decide(req, *, admin, approve, note=""):
    req.refresh_from_db()
    if req.status != LeaveRequest.AWAITING_ADMIN:
        raise LeaveError("This request is not waiting for approval.")
    req.status = LeaveRequest.APPROVED if approve else LeaveRequest.REJECTED
    req.decided_by, req.decided_at, req.decision_note = admin, timezone.now(), note
    req.save()
    if approve:
        notify(req.faculty, "Your leave was approved.", f"/leaves/{req.pk}/")
        for a in leave_adjustments(req):
            notify(a.substitute, f"Reminder: you will take {_label(a)} for {req.faculty.full_name}.", "/faculty-home/")
    else:
        subs = {a.substitute for a in req.adjustments.exclude(status=Adjustment.CANCELLED) if a.substitute}
        _close_adjustments(req)
        notify(req.faculty, "Your leave was rejected." + (f" {note}" if note else ""), f"/leaves/{req.pk}/")
        for s in subs:
            notify(s, f"The leave of {req.faculty.full_name} was rejected; you are not needed for those periods.")


@transaction.atomic
def cancel_request(req, *, user):
    req.refresh_from_db()
    if req.status in (LeaveRequest.REJECTED, LeaveRequest.CANCELLED):
        raise LeaveError("This leave is already closed.")
    if user.is_faculty_role and (req.faculty_id != user.pk or req.status == LeaveRequest.APPROVED):
        raise LeaveError("An approved leave can only be cancelled by the admin.")
    if AttendanceSession.objects.filter(adjustment__leave_request=req).exists():
        raise LeaveError("Attendance has already been taken by substitutes for this leave, so it cannot be cancelled.")
    subs = {a.substitute for a in req.adjustments.exclude(status=Adjustment.CANCELLED) if a.substitute}
    req.status = LeaveRequest.CANCELLED
    req.save(update_fields=["status"])
    _close_adjustments(req)
    for s in subs:
        notify(s, f"The leave of {req.faculty.full_name} was cancelled; you are not needed for those periods.")


# ------------------------------------------------------------------ return adjustments

def return_candidates(req, covering, date):
    """Periods of `covering` (a substitute) on `date` that the applicant could take in exchange."""
    ctx = DayContext(date)
    out = []
    index = ScheduleIndex(date, date)
    for c in index.classes:
        if index.holiday_reason(date, c.pk):
            continue
        for e in index.entries_for(date, c.pk):
            if e.faculty_id != covering.pk:
                continue
            if (c.pk, date, e.period_no) in index.sessions or index.adjustments.get((c.pk, date, e.period_no)):
                continue
            if Adjustment.objects.filter(school_class=c, date=date, period_no=e.period_no).exclude(
                    status=Adjustment.CANCELLED).exists():
                continue
            ok = eligible_faculty(c, e.subject, date, e.period_no, original_faculty=covering, ctx=ctx)
            if req.faculty_id in {f.pk for f in ok}:
                out.append((c, e))
    return out


@transaction.atomic
def offer_return(req, *, user, school_class, date, period_no, same_subject, subject=None):
    """The applicant offers to take one of the substitute's periods on another date, in exchange."""
    req.refresh_from_db()
    if req.status not in LeaveRequest.SUBMITTED:
        raise LeaveError("A return can only be offered for a submitted leave.")
    if user.is_faculty_role and (req.faculty_id != user.pk or date < today()):
        raise LeaveError("Choose a date that has not passed.")
    index = ScheduleIndex(date, date)
    entry = next((e for e in index.entries_for(date, school_class.pk) if e.period_no == period_no), None)
    if entry is None or index.holiday_reason(date, school_class.pk):
        raise LeaveError("That period is not in the timetable on that date.")
    covering = entry.faculty
    if covering.pk not in {a.substitute_id for a in leave_adjustments(req) if a.substitute_id}:
        raise LeaveError("You can only offer to take a period of someone who covered for you.")
    if Adjustment.objects.filter(school_class=school_class, date=date, period_no=period_no).exclude(
            status=Adjustment.CANCELLED).exists() or (school_class.pk, date, period_no) in index.sessions:
        raise LeaveError("That period already has an adjustment or attendance.")
    adj = Adjustment.objects.create(
        leave_request=req, kind=Adjustment.RETURN, school_class=school_class, date=date, period_no=period_no,
        original_faculty=covering, original_subject=entry.subject)
    set_adjustment(adj, user=user, substitute=req.faculty, same_subject=same_subject, subject=subject)
    return adj


# ------------------------------------------------------------------ balances & admin lists

def leave_year_bounds(year):
    return datetime.date(year, 1, 1), datetime.date(year, 12, 31)


def leave_balance(faculty, year=None):
    """Per leave type: allowed, used (approved only), waiting (submitted, not yet approved), remaining."""
    year = year or today().year
    lo, hi = leave_year_bounds(year)
    rows = []
    for t in LeaveType.objects.filter(active=True):
        days = LeaveDay.objects.filter(request__faculty=faculty, request__leave_type=t, date__range=(lo, hi))
        used = sum((d.days_value for d in days.filter(request__status=LeaveRequest.APPROVED)), Decimal("0"))
        waiting = sum((d.days_value for d in days.filter(request__status__in=(
            LeaveRequest.AWAITING_CONSENT, LeaveRequest.AWAITING_ADMIN, LeaveRequest.DRAFT))), Decimal("0"))
        remaining = t.days_per_year - used
        rows.append({"type": t, "allowed": t.days_per_year, "used": used, "waiting": waiting,
                     "remaining": remaining, "exhausted": remaining <= 0})
    return rows


def balance_warning(req):
    """A text warning if approving this request exceeds (or has exhausted) the faculty's balance, else ''."""
    row = next((r for r in leave_balance(req.faculty, req.from_date.year) if r["type"].pk == req.leave_type_id), None)
    if row is None:
        return ""
    if req.status == LeaveRequest.APPROVED:     # already deducted
        return f"{req.leave_type.name} balance is now exhausted." if row["exhausted"] else ""
    if row["exhausted"]:
        return f"{req.leave_type.name} balance is exhausted ({row['used']} of {row['allowed']} days used)."
    if req.total_days > row["remaining"]:
        return (f"This leave ({req.total_days} days) exceeds the remaining {req.leave_type.name} balance "
                f"({row['remaining']} days).")
    return ""


def unadjusted_periods(on=None):
    """Periods in a submitted/approved leave with no accepted substitute, nearest dates first."""
    on = on or today()
    qs = (Adjustment.objects.filter(kind=Adjustment.LEAVE, status__in=(
        Adjustment.UNASSIGNED, Adjustment.PENDING, Adjustment.DECLINED),
        leave_request__status__in=LeaveRequest.SUBMITTED)
          .select_related("school_class", "original_faculty", "original_subject", "substitute", "leave_request",
                          "leave_request__leave_type"))
    return sorted(qs, key=lambda a: (abs((a.date - on).days), a.date, a.period_no))
