"""Timetable rules: which version is in force, parsing uploads, validating, saving."""
import datetime

from django.conf import settings
from django.db import transaction

from accounts.models import User
from academics.models import Subject

from .models import DAY_NAMES, Timetable, TimetableEntry

HEADERS = ["day", "period", "start_time", "end_time", "subject", "faculty"]
PERIODS = range(1, settings.PERIODS_PER_DAY + 1)
DAYS = range(settings.WORKING_DAYS)


def timetable_in_force(school_class, date):
    """The latest version whose effective_from is on or before `date` (or None)."""
    return (Timetable.objects.filter(school_class=school_class, effective_from__lte=date)
            .order_by("-effective_from").first())


def fmt_time(t):
    return t.strftime("%H:%M")


def parse_time(text):
    text = str(text).strip()
    for f in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%H.%M"):
        try:
            return datetime.datetime.strptime(text, f).time()
        except ValueError:
            pass
    raise ValueError(f"Cannot read time '{text}' (use HH:MM, e.g. 09:00)")


def parse_day(text):
    t = str(text).strip().lower()
    for i, name in enumerate(DAY_NAMES):
        if t[:3] == name[:3].lower():
            return i
    if t.isdigit() and 1 <= int(t) <= len(DAY_NAMES):
        return int(t) - 1
    raise ValueError(f"Unknown day '{text}' (use Mon, Tue, ... Sat)")


def parse_upload_rows(school_class, rows):
    """Turn uploaded rows into cleaned dicts. Returns (cleaned, errors) where errors = [(line, message)]."""
    subjects = list(school_class.subjects.all())
    by_code = {s.code.lower(): s for s in subjects}
    by_name = {s.name.lower(): s for s in subjects}
    faculty = list(User.objects.filter(role=User.FACULTY, is_active=True))
    f_by_id = {f.username.lower(): f for f in faculty}
    f_by_name = {f.full_name.lower(): f for f in faculty}
    cleaned, errors = [], []
    for r in rows:
        line = r["_line"]
        try:
            day = parse_day(r.get("day", ""))
            raw_p = r.get("period") or r.get("period_no") or ""
            if not str(raw_p).strip().isdigit() or int(raw_p) not in PERIODS:
                raise ValueError(f"Period must be a number from 1 to {settings.PERIODS_PER_DAY}")
            period = int(raw_p)
            start = parse_time(r.get("start_time") or r.get("start") or "")
            end = parse_time(r.get("end_time") or r.get("end") or "")
            key = (r.get("subject") or "").strip().lower()
            subject = by_code.get(key) or by_name.get(key)
            if not subject:
                raise ValueError(f"Subject '{r.get('subject', '')}' is not a subject of this class")
            fkey = (r.get("faculty") or "").strip().lower()
            fac = f_by_id.get(fkey) or f_by_name.get(fkey)
            if not fac:
                raise ValueError(f"Faculty '{r.get('faculty', '')}' not found (use the faculty User ID)")
        except ValueError as exc:
            errors.append((line, str(exc)))
            continue
        cleaned.append({"day": day, "period": period, "start": fmt_time(start), "end": fmt_time(end),
                        "subject_id": subject.pk, "faculty_id": fac.pk, "line": line})
    return cleaned, errors


def validate_entries(school_class, effective_from, cleaned, exclude_timetable_id=None):
    """Rules that apply to a whole timetable. Returns a list of error strings (empty = OK)."""
    errors = []
    seen = {}
    times = {}
    for e in cleaned:
        slot = (e["day"], e["period"])
        where = f"{DAY_NAMES[e['day']]} period {e['period']}"
        if slot in seen:
            errors.append(f"{where} is listed more than once.")
        seen[slot] = e
        if e["end"] <= e["start"]:
            errors.append(f"{where}: end time must be after start time.")
        times.setdefault(e["period"], set()).add((e["start"], e["end"]))
    for p, ts in sorted(times.items()):
        if len(ts) > 1:
            errors.append(f"Period {p} has different timings on different days. "
                          "Use the same start and end time for a period on every day.")
    # A teacher cannot be in two classes at once (checked against other classes' timetables in force).
    names = {u.pk: u.full_name for u in User.objects.filter(pk__in={e["faculty_id"] for e in cleaned})}
    for other in school_class.__class__.objects.exclude(pk=school_class.pk):
        tt = timetable_in_force(other, effective_from)
        if not tt or tt.pk == exclude_timetable_id:
            continue
        theirs = {(x.day, x.period_no): x.faculty_id for x in tt.entries.all()}
        for e in cleaned:
            if theirs.get((e["day"], e["period"])) == e["faculty_id"]:
                errors.append(f"{names[e['faculty_id']]} is already teaching {other.name} on "
                              f"{DAY_NAMES[e['day']]} period {e['period']}.")
    # subject must belong to the class
    valid_subjects = set(school_class.subjects.values_list("pk", flat=True))
    for e in cleaned:
        if e["subject_id"] not in valid_subjects:
            errors.append(f"Subject on {DAY_NAMES[e['day']]} period {e['period']} does not belong to this class.")
    return errors


@transaction.atomic
def save_entries(timetable, cleaned):
    """Replace all entries of `timetable` with `cleaned`."""
    timetable.entries.all().delete()
    TimetableEntry.objects.bulk_create([
        TimetableEntry(timetable=timetable, day=e["day"], period_no=e["period"],
                       start_time=parse_time(e["start"]), end_time=parse_time(e["end"]),
                       subject_id=e["subject_id"], faculty_id=e["faculty_id"])
        for e in cleaned])


def entries_to_cleaned(timetable):
    return [{"day": e.day, "period": e.period_no, "start": fmt_time(e.start_time), "end": fmt_time(e.end_time),
             "subject_id": e.subject_id, "faculty_id": e.faculty_id} for e in timetable.entries.all()]


def build_grid(cleaned):
    """Rows for a weekly grid display: one row per period, one cell per day."""
    subjects = {s.pk: s for s in Subject.objects.filter(pk__in={e["subject_id"] for e in cleaned})}
    users = {u.pk: u for u in User.objects.filter(pk__in={e["faculty_id"] for e in cleaned})}
    cell = {(e["day"], e["period"]): e for e in cleaned}
    rows = []
    for p in PERIODS:
        period_times = next(((e["start"], e["end"]) for e in cleaned if e["period"] == p), None)
        cells = []
        for d in DAYS:
            e = cell.get((d, p))
            cells.append({"subject": subjects[e["subject_id"]], "faculty": users[e["faculty_id"]]} if e else None)
        rows.append({"period": p, "times": period_times, "cells": cells})
    return rows
