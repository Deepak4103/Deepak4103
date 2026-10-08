import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from academics.models import SchoolClass, Subject, is_holiday
from accounts.decorators import admin_required, faculty_required
from accounts.models import User

from . import services as svc
from .forms import AttendanceForm
from .models import AttendanceSession


@faculty_required
def faculty_home(request):
    todays, pending = svc.faculty_day_and_pending(request.user)
    today = svc.today()
    older = [s for s in pending if s.date < today]
    return render(request, "attendance/faculty_home.html", {
        "today": today, "slots": todays, "pending": pending, "older": older,
        "pending_today": [s for s in pending if s.date == today]})


@login_required
def mark_attendance(request, class_pk, date, period):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    user = request.user
    session = (AttendanceSession.objects.filter(school_class=c, date=date, period_no=period)
               .select_related("subject", "taken_by", "scheduled_subject", "scheduled_faculty").first())
    entry = svc.find_entry(c, date, period)
    if session:
        if not svc.can_view_session(user, session):
            raise PermissionDenied
        if not svc.can_edit_session(user, session):
            messages.error(request, "This record is locked. Ask the admin to unlock it if it needs a correction.")
            return redirect("session_detail", session.pk)
        subject, faculty = session.subject, session.taken_by
        absent_ids = set(session.records.filter(present=False).values_list("student_id", flat=True))
        initial = {"topic": session.topic, "remarks": session.remarks}
    else:
        if entry is None:
            raise Http404("No such period in the timetable.")
        if user.is_faculty_role and entry.faculty_id != user.pk:
            raise PermissionDenied
        if date > svc.today():
            messages.error(request, "Attendance cannot be entered for a future date.")
            return redirect("home")
        if is_holiday(date, c):
            messages.error(request, "That date is a holiday.")
            return redirect("home")
        subject, faculty = entry.subject, entry.faculty
        absent_ids, initial = set(), None

    students = list(c.students.all())
    form = AttendanceForm(request.POST or None, initial=initial)
    if request.method == "POST":
        absent_ids = {int(x) for x in request.POST.getlist("absent") if x.isdigit()}
        if form.is_valid():
            try:
                if session:
                    svc.update_attendance(session, user=user, absent_ids=absent_ids,
                                          topic=form.cleaned_data["topic"], remarks=form.cleaned_data["remarks"])
                    saved = session
                else:
                    saved = svc.save_attendance(
                        school_class=c, date=date, period_no=period, entry=entry, user=user, absent_ids=absent_ids,
                        topic=form.cleaned_data["topic"], remarks=form.cleaned_data["remarks"])
            except svc.DuplicateAttendance as exc:
                messages.error(request, str(exc))
                return redirect("mark_attendance", c.pk, date, period)
            except svc.AttendanceError as exc:
                form.add_error(None, str(exc))
            else:
                present, absent = svc.session_counts(saved)
                messages.success(request, f"Saved: {present} present, {absent} absent.")
                return redirect("home" if user.is_faculty_role else "monitor")
    sched = entry
    return render(request, "attendance/mark.html", {
        "c": c, "date": date, "period": period, "subject": subject, "faculty": faculty, "entry": sched,
        "session": session, "students": students, "absent_ids": absent_ids, "form": form,
        "absent_count": len(absent_ids & {s.pk for s in students}), "total": len(students),
        "audits": session.audits.select_related("user") if session and user.is_admin_role else []})


@login_required
def session_detail(request, pk):
    s = get_object_or_404(AttendanceSession.objects.select_related(
        "school_class", "subject", "taken_by", "scheduled_subject", "scheduled_faculty"), pk=pk)
    if not svc.can_view_session(request.user, s):
        raise PermissionDenied
    recs = list(s.records.select_related("student").order_by("student__roll_no"))
    return render(request, "attendance/detail.html", {
        "s": s, "absent": [r.student for r in recs if not r.present],
        "present_n": sum(1 for r in recs if r.present), "records": recs,
        "can_edit": svc.can_edit_session(request.user, s),
        "audits": s.audits.select_related("user") if request.user.is_admin_role else []})


@admin_required
@require_POST
def session_unlock(request, pk):
    s = get_object_or_404(AttendanceSession, pk=pk)
    unlock = request.POST.get("unlock") == "1"
    svc.set_unlocked(s, unlock)
    messages.success(request, "Unlocked for the faculty to edit." if unlock else "Locked.")
    return redirect("session_detail", s.pk)


@login_required
def records(request):
    """Past attendance and logs. Faculty see their own subjects; admin sees everything."""
    user = request.user
    qs = AttendanceSession.objects.select_related("school_class", "subject", "taken_by")
    if user.is_faculty_role:
        qs = qs.filter(Q(taken_by=user) | Q(subject__allotment__faculty=user))
    g = request.GET
    class_id, subject_id, fac_id = g.get("class"), g.get("subject"), g.get("faculty")
    if class_id and class_id.isdigit():
        qs = qs.filter(school_class_id=int(class_id))
    if subject_id and subject_id.isdigit():
        qs = qs.filter(subject_id=int(subject_id))
    if fac_id and fac_id.isdigit() and user.is_admin_role:
        qs = qs.filter(taken_by_id=int(fac_id))
    for key, lookup in (("from", "date__gte"), ("to", "date__lte")):
        try:
            qs = qs.filter(**{lookup: datetime.date.fromisoformat(g.get(key, ""))})
        except ValueError:
            pass
    qs = qs.annotate(absent_n=Count("records", filter=Q(records__present=False)),
                     total_n=Count("records")).order_by("-date", "period_no")
    subjects = Subject.objects.select_related("school_class")
    if user.is_faculty_role:
        subjects = subjects.filter(allotment__faculty=user)
    return render(request, "attendance/records.html", {
        "sessions": qs[:200], "classes": SchoolClass.objects.all(), "subjects": subjects,
        "faculty": User.objects.filter(role=User.FACULTY), "g": g})


@admin_required
def monitor(request):
    try:
        date = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        date = svc.today()
    class_id = request.GET.get("class")
    class_id = int(class_id) if class_id and class_id.isdigit() else None
    index = svc.ScheduleIndex(date, date)
    groups, holiday_notes = [], []
    done = pending = 0
    for c in index.classes:
        if class_id and c.pk != class_id:
            continue
        reason = index.holiday_reason(date, c.pk)
        if reason:
            holiday_notes.append((c, reason))
            continue
        slots = index.slots(date, class_id=c.pk)
        done += sum(1 for s in slots if s.completed)
        pending += sum(1 for s in slots if not s.completed)
        groups.append((c, slots))
    return render(request, "attendance/monitor.html", {
        "date": date, "groups": groups, "holiday_notes": holiday_notes, "done": done, "pending": pending,
        "classes": SchoolClass.objects.all(), "class_id": class_id,
        "is_future": date > svc.today(),
        "prev": date - datetime.timedelta(days=1), "next": date + datetime.timedelta(days=1)})
