"""The seven admin reports. Each builder takes Filters and returns a Report (title, columns, rows)
that the screen, the Excel export and the PDF export all share."""
import datetime
from dataclasses import dataclass, field

from django.db.models import Count, Q

from academics.models import SchoolClass, Subject, shortage_threshold
from accounts.models import User
from attendance import services as att
from attendance.models import AttendanceRecord, AttendanceSession
from leaves.models import Adjustment, LeaveRequest

from .stats import below, lookups, pct, sessions, student_subject_counts, student_totals


@dataclass
class Report:
    title: str
    columns: list
    rows: list
    subtitle: str = ""
    notes: list = field(default_factory=list)
    flags: list = field(default_factory=list)       # parallel to rows: "bad" highlights a row

    def flag(self, i):
        return self.flags[i] if i < len(self.flags) else ""


def _pct_text(p):
    return "-" if p is None else f"{p}%"


def _date(d):
    return d.strftime("%d-%m-%Y") if d else ""


def describe(f, *extra):
    """A one-line description of the filters that were applied."""
    parts = []
    if f.school_class:
        parts.append(f"Class: {f.school_class.name}")
    if f.subject_code:
        parts.append(f"Subject: {f.subject_code}")
    if f.faculty:
        parts.append(f"Faculty: {f.faculty.full_name}")
    if f.date:
        parts.append(f"Date: {_date(f.date)}")
    if f.date_from or f.date_to:
        parts.append(f"From {_date(f.date_from) or 'start'} to {_date(f.date_to) or 'today'}")
    parts.extend(extra)
    return " | ".join(parts) or "All classes, subjects, faculty and dates"


def _taken_text(s):
    """Faculty name, with the original faculty when the period was an adjustment."""
    who = s.taken_by.full_name
    if s.adjustment_id:
        who += f" (adjustment for {s.adjustment.original_faculty.full_name})"
    return who


def _subject_text(s):
    """Subject taught; with the timetable subject when it differs."""
    if s.scheduled_subject_id != s.subject_id:
        return f"{s.subject.name} (timetable: {s.scheduled_subject.name})"
    return s.subject.name


# ------------------------------------------------------------------ 1. student-wise

def student_wise(f):
    c = f.school_class
    subjects = list(c.subjects.all())
    if f.subject_code:
        subjects = [s for s in subjects if s.code.lower() == f.subject_code.lower()]
    counts = student_subject_counts(f)
    threshold = shortage_threshold()
    cols = ["Roll no", "Name"] + [f"{s.name} ({s.code}): attended/held, %" for s in subjects] + [
        "Total held", "Total attended", "Overall %"]
    rows, flags = [], []
    for st in c.students.all():
        cells, held_all, att_all = [st.roll_no, st.name], 0, 0
        for s in subjects:
            held, a = counts.get((st.pk, s.pk), (0, 0))
            cells.append(f"{a}/{held} ({_pct_text(pct(a, held))})" if held else "-")
            held_all, att_all = held_all + held, att_all + a
        cells += [held_all, att_all, _pct_text(pct(att_all, held_all))]
        rows.append(cells)
        flags.append("bad" if below(att_all, held_all, threshold) else "")
    return Report("Student-wise attendance", cols, rows, describe(f),
                  [f"Classes held are the periods actually entered under each subject taught. "
                   f"Rows in red are below {threshold}%."], flags)


# ------------------------------------------------------------------ 2. class / subject summary

def class_subject_summary(f):
    rec = (AttendanceRecord.objects.filter(**lookups(f, "session__"))
           .values("session__school_class_id", "session__subject_id")
           .annotate(n_present=Count("id", filter=Q(present=True)), n_absent=Count("id", filter=Q(present=False))))
    marks = {(r["session__school_class_id"], r["session__subject_id"]): (r["n_present"], r["n_absent"]) for r in rec}
    held = {}
    faculty = {}
    for s in sessions(f).select_related("taken_by"):
        key = (s.school_class_id, s.subject_id)
        held[key] = held.get(key, 0) + 1
        faculty.setdefault(key, set()).add(s.taken_by.full_name)
    classes = {c.pk: c for c in SchoolClass.objects.all()}
    subjects = {s.pk: s for s in Subject.objects.all()}
    rows, last_class, tot = [], None, [0, 0, 0]

    def flush(cls):
        if cls is not None:
            rows.append([classes[cls].name, "ALL SUBJECTS", "", tot[0], tot[1], tot[2], _pct_text(pct(tot[1], tot[1] + tot[2]))])

    for (cid, sid) in sorted(held, key=lambda k: (classes[k[0]].name, subjects[k[1]].name)):
        if cid != last_class:
            flush(last_class)
            last_class, tot = cid, [0, 0, 0]
        p, a = marks.get((cid, sid), (0, 0))
        rows.append([classes[cid].name, f"{subjects[sid].name} ({subjects[sid].code})", ", ".join(sorted(faculty[(cid, sid)])),
                     held[(cid, sid)], p, a, _pct_text(pct(p, p + a))])
        tot = [tot[0] + held[(cid, sid)], tot[1] + p, tot[2] + a]
    flush(last_class)
    return Report("Class-wise and subject-wise summary",
                  ["Class", "Subject", "Faculty", "Classes held", "Present (student-periods)",
                   "Absent (student-periods)", "Average attendance %"], rows, describe(f),
                  ["Classes held = periods actually entered. Student-periods = one student in one period."])


# ------------------------------------------------------------------ 3. daily report

def daily(f):
    date = f.date or att.today()
    index = att.ScheduleIndex(date, date)
    counts = {r["session_id"]: (r["p"], r["a"]) for r in
              AttendanceRecord.objects.filter(session__date=date).values("session_id").annotate(
                  p=Count("id", filter=Q(present=True)), a=Count("id", filter=Q(present=False)))}
    rows, flags, notes = [], [], []
    for c in index.classes:
        if f.school_class and c != f.school_class:
            continue
        reason = index.holiday_reason(date, c.pk)
        if reason:
            notes.append(f"{c.name}: holiday ({reason})")
            continue
        for slot in index.slots(date, class_id=c.pk):
            s = slot.session
            subject = slot.subject
            if f.subject_code and subject.code.lower() != f.subject_code.lower():
                continue
            if f.faculty and slot.faculty.pk != f.faculty.pk:
                if not (slot.unadjusted and slot.entry.faculty_id == f.faculty.pk):
                    continue
            if s:
                status = "Entered (adjusted)" if s.adjustment_id else "Entered"
                p, a = counts.get(s.pk, (0, 0))
                present, absent, topic, remarks = p, a, s.topic, s.remarks
                subj_text, who = _subject_text(s), _taken_text(s)
            else:
                status = "On leave - no substitute" if slot.unadjusted else (
                    "Pending (adjusted)" if slot.is_adjusted else "Pending")
                present = absent = ""
                topic = remarks = ""
                subj_text = subject.name + (f" (timetable: {slot.entry.subject.name})"
                                            if subject.pk != slot.entry.subject_id else "")
                who = slot.faculty.full_name + (f" (adjustment for {slot.adjusted_for.full_name})" if slot.is_adjusted else "")
                if slot.unadjusted:
                    who = f"{slot.entry.faculty.full_name} (on leave)"
            rows.append([c.name, slot.period_no,
                         f"{slot.entry.start_time:%H:%M}-{slot.entry.end_time:%H:%M}", subj_text, who, status,
                         present, absent, topic, remarks])
            flags.append("" if s else "bad")
    rows_flags = sorted(zip(rows, flags), key=lambda x: (x[0][0], x[0][1]))
    rows, flags = [r for r, _ in rows_flags], [fl for _, fl in rows_flags]
    return Report(f"Daily report - {date.strftime('%A, %d-%m-%Y')}",
                  ["Class", "Period", "Time", "Subject", "Faculty", "Status", "Present", "Absent", "Topic covered", "Remarks"],
                  rows, describe(f) if f.school_class or f.subject_code or f.faculty else f"Date: {_date(date)}",
                  notes + ["Rows in red are periods without attendance."], flags)


# ------------------------------------------------------------------ 4. shortage list

def shortage(f):
    threshold = f.threshold or shortage_threshold()
    totals = student_totals(f)
    per_subject = student_subject_counts(f) if not f.subject_code else {}
    subjects = {s.pk: s for s in Subject.objects.all()}
    from academics.models import Student
    students = Student.objects.select_related("school_class")
    if f.school_class:
        students = students.filter(school_class=f.school_class)
    out = []
    for st in students:
        held, a = totals.get(st.pk, (0, 0))
        if not below(a, held, threshold):
            continue
        low = [f"{subjects[sid].name} {pct(x, h)}%" for (stid, sid), (h, x) in per_subject.items()
               if stid == st.pk and below(x, h, threshold)]
        out.append((pct(a, held), [st.school_class.name, st.roll_no, st.name, held, a, _pct_text(pct(a, held)),
                                   "; ".join(sorted(low))]))
    out.sort(key=lambda x: (x[0], x[1][1]))
    rows = [r for _, r in out]
    return Report(f"Attendance shortage list (below {threshold}%)",
                  ["Class", "Roll no", "Name", "Classes held", "Attended", "Overall %", "Subjects below threshold"],
                  rows, describe(f, f"Threshold: {threshold}%"),
                  [f"Students whose attendance is below {threshold}%, lowest first. Students with no classes held yet are not listed."],
                  ["bad"] * len(rows))


# ------------------------------------------------------------------ 5. faculty log

def faculty_log(f):
    qs = (sessions(f).select_related("taken_by", "subject", "scheduled_subject", "school_class",
                                     "adjustment__original_faculty")
          .order_by("taken_by__full_name", "subject__name", "date", "period_no"))
    rows = []
    for s in qs:
        note = f"Adjustment for {s.adjustment.original_faculty.full_name}" if s.adjustment_id else ""
        if s.scheduled_subject_id != s.subject_id:
            note += (" - " if note else "") + f"timetable subject: {s.scheduled_subject.name}"
        rows.append([s.taken_by.full_name, f"{s.subject.name} ({s.subject.code})", s.school_class.name,
                     _date(s.date), s.period_no, s.topic, s.remarks, note])
    return Report("Faculty log - topics covered",
                  ["Faculty", "Subject", "Class", "Date", "Period", "Topic covered", "Remarks", "Note"], rows, describe(f),
                  ["Adjusted periods are credited to the substitute under the subject actually taught."])


# ------------------------------------------------------------------ 6. leave & adjustment register

def leave_register(f):
    reqs = LeaveRequest.objects.filter(status__in=LeaveRequest.SUBMITTED).select_related("faculty", "leave_type")
    if f.faculty:
        reqs = reqs.filter(faculty=f.faculty)
    if f.date_from:
        reqs = reqs.filter(to_date__gte=f.date_from)
    if f.date_to:
        reqs = reqs.filter(from_date__lte=f.date_to)
    adjs = (Adjustment.objects.filter(leave_request__in=reqs).exclude(status=Adjustment.CANCELLED)
            .select_related("school_class", "original_subject", "subject_taught", "substitute", "made_by",
                            "original_faculty", "leave_request__faculty", "leave_request__leave_type"))
    if f.school_class:
        adjs = adjs.filter(school_class=f.school_class)
    if f.subject_code:
        adjs = adjs.filter(Q(original_subject__code__iexact=f.subject_code) | Q(subject_taught__code__iexact=f.subject_code))
    if f.date_from:
        adjs = adjs.filter(date__gte=f.date_from)
    if f.date_to:
        adjs = adjs.filter(date__lte=f.date_to)
    rows, seen = [], set()
    for a in sorted(adjs, key=lambda a: (a.leave_request.faculty.full_name, a.date, a.period_no)):
        r = a.leave_request
        seen.add(r.pk)
        rows.append([
            r.faculty.full_name, r.leave_type.name, r.get_status_display(), _date(a.date), a.period_no,
            a.school_class.name, a.original_subject.name,
            a.substitute.full_name if a.substitute else "-",
            a.subject_taught.name if a.subject_taught else "-",
            "Return (applicant takes substitute's period)" if a.kind == Adjustment.RETURN else "Leave cover",
            "-" if not a.subject_taught_id else ("Same" if a.same_subject else "Different"),
            a.get_status_display(),
            ("-" if not a.made_by_role else ("Admin" if a.made_by_role == "admin" else "Faculty"))])
    if not f.school_class and not f.subject_code:       # leaves with no affected periods still count as leave
        for r in reqs:
            if r.pk not in seen:
                rows.append([r.faculty.full_name, r.leave_type.name, r.get_status_display(),
                             f"{_date(r.from_date)} to {_date(r.to_date)}", "-", "-", "-", "-", "-",
                             "No periods affected", "-", "-", "-"])
    rows.sort(key=lambda r: (r[0], r[3]))
    return Report("Leave and adjustment register",
                  ["Faculty on leave", "Leave type", "Leave status", "Date", "Period", "Class", "Timetable subject",
                   "Taken by", "Subject taught", "Kind", "Same / different subject", "Adjustment status", "Arranged by"],
                  rows, describe(f),
                  ["Includes leave that is awaiting acceptance, awaiting approval or approved."])


# ------------------------------------------------------------------ 7. faculty workload

def workload(f):
    base = sessions(f)
    own = {r["taken_by"]: r["n"] for r in base.filter(adjustment__isnull=True).values("taken_by").annotate(n=Count("id"))}
    others = {r["taken_by"]: r["n"] for r in base.filter(adjustment__isnull=False).values("taken_by").annotate(n=Count("id"))}
    given = {r["adjustment__original_faculty"]: r["n"] for r in
             base.filter(adjustment__isnull=False).values("adjustment__original_faculty").annotate(n=Count("id"))}
    fac = User.objects.filter(role=User.FACULTY)
    if f.faculty:
        fac = fac.filter(pk=f.faculty.pk)
    rows, tot = [], [0, 0, 0]
    for u in fac:
        o, ot, g = own.get(u.pk, 0), others.get(u.pk, 0), given.get(u.pk, 0)
        rows.append([u.full_name, o, ot, g, o + ot])
        tot = [tot[0] + o, tot[1] + ot, tot[2] + g]
    rows.append(["TOTAL", tot[0], tot[1], tot[2], tot[0] + tot[1]])
    return Report("Faculty workload",
                  ["Faculty", "Own periods taken", "Adjustment periods taken for others", "Periods given away",
                   "Total periods taken"], rows, describe(f),
                  ["Counts are periods whose attendance was actually entered. 'Given away' = the faculty's own "
                   "periods that a substitute took."])


@dataclass
class ReportDef:
    slug: str
    title: str
    description: str
    fields: tuple
    builder: object
    needs_class: bool = False


REPORTS = [
    ReportDef("student-wise", "Student-wise attendance",
              "Classes held, attended and percentage for each student, per subject and overall.",
              ("school_class", "subject", "faculty", "date_from", "date_to"), student_wise, needs_class=True),
    ReportDef("class-subject", "Class and subject summary",
              "Classes held and average attendance for each class and subject.",
              ("school_class", "subject", "faculty", "date_from", "date_to"), class_subject_summary),
    ReportDef("daily", "Daily report", "Every period of a date with attendance, topic covered and adjustments.",
              ("date", "school_class", "subject", "faculty"), daily),
    ReportDef("shortage", "Shortage list", "Students below the attendance threshold.",
              ("school_class", "subject", "faculty", "date_from", "date_to", "threshold"), shortage),
    ReportDef("faculty-log", "Faculty log", "Topics covered by each faculty, subject-wise, by date.",
              ("school_class", "subject", "faculty", "date_from", "date_to"), faculty_log),
    ReportDef("leave-register", "Leave and adjustment register",
              "Who was on leave, which periods were adjusted, who took them and how.",
              ("school_class", "subject", "faculty", "date_from", "date_to"), leave_register),
    ReportDef("workload", "Faculty workload", "Own periods, adjustment periods taken for others, periods given away.",
              ("school_class", "subject", "faculty", "date_from", "date_to"), workload),
]
BY_SLUG = {r.slug: r for r in REPORTS}
