"""Attendance statistics.

The rule: percentages come only from classes actually held, i.e. attendance sessions that were entered
(never from the timetable), and are grouped by the subject actually taught in that session."""
import datetime
from dataclasses import dataclass

from django.db.models import Count, Q

from attendance.models import AttendanceRecord, AttendanceSession


@dataclass
class Filters:
    school_class: object = None          # SchoolClass
    subject_code: str = ""               # matches the subject taught (any class)
    faculty: object = None               # User: credited with the period
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    date: datetime.date | None = None    # daily report
    threshold: int | None = None         # shortage report


def pct(attended, held):
    """Percentage to one decimal, or None when nothing was held."""
    return None if not held else round(attended * 100 / held, 1)


def below(attended, held, threshold):
    """True if attendance is strictly below the threshold. Exact arithmetic, so 75/100 is not 'below 75'."""
    return held > 0 and attended * 100 < threshold * held


def lookups(f, prefix=""):
    """ORM filter keywords selecting attendance sessions (prefix 'session__' when filtering records)."""
    q = {}
    if f.school_class:
        q[prefix + "school_class"] = f.school_class
    if f.subject_code:
        q[prefix + "subject__code__iexact"] = f.subject_code
    if f.faculty:
        q[prefix + "taken_by"] = f.faculty
    if f.date_from:
        q[prefix + "date__gte"] = f.date_from
    if f.date_to:
        q[prefix + "date__lte"] = f.date_to
    if f.date:
        q[prefix + "date"] = f.date
    return q


def sessions(f):
    return AttendanceSession.objects.filter(**lookups(f))


def student_subject_counts(f):
    """{(student_id, subject_id): (held, attended)} for the filtered sessions."""
    rows = (AttendanceRecord.objects.filter(**lookups(f, "session__"))
            .values("student_id", "session__subject_id")
            .annotate(held=Count("id"), attended=Count("id", filter=Q(present=True))))
    return {(r["student_id"], r["session__subject_id"]): (r["held"], r["attended"]) for r in rows}


def student_totals(f):
    """{student_id: (held, attended)} over all subjects in the filtered sessions."""
    out = {}
    for (sid, _), (held, att) in student_subject_counts(f).items():
        h, a = out.get(sid, (0, 0))
        out[sid] = (h + held, a + att)
    return out
