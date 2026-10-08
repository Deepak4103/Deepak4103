import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from academics.models import SchoolClass, Subject
from accounts.decorators import admin_required, faculty_required
from accounts.models import User
from attendance.models import AttendanceSession
from attendance.services import today

from . import services as svc
from .forms import LeaveApplyForm, LeaveTypeForm
from .models import Adjustment, LeaveRequest, LeaveType, Notification
from .periods import PERIODS


def _own_or_admin(user, req):
    if not (user.is_admin_role or req.faculty_id == user.pk):
        raise PermissionDenied


# ------------------------------------------------------------------ faculty

@faculty_required
def my_leaves(request):
    return render(request, "leaves/my_leaves.html", {
        "requests": request.user.leave_requests.select_related("leave_type"),
        "balance": svc.leave_balance(request.user)})


@login_required
def leave_apply(request):
    admin = request.user.is_admin_role
    form = LeaveApplyForm(request.POST or None, admin=admin)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        faculty = d["faculty"] if admin else request.user
        try:
            req = svc.create_leave_request(
                faculty=faculty, leave_type=d["leave_type"], from_date=d["from_date"], to_date=d["to_date"],
                scope=d["scope"], periods=",".join(d["periods"]), reason=d["reason"], created_by=request.user)
        except svc.LeaveError as exc:
            form.add_error(None, str(exc))
        else:
            n = svc.leave_adjustments(req).count()
            if admin:
                messages.success(request, f"Leave entered and approved. {n} period(s) need a substitute.")
            else:
                messages.success(request, f"{n} period(s) fall in your leave. Choose a substitute and subject for each.")
            return redirect("leave_detail", req.pk)
    return render(request, "leaves/apply.html", {"form": form, "admin": admin, "today": today()})


def _rows(req, user):
    """One entry per adjustment row, with the eligible substitutes and whether this user may edit it."""
    ctx_cache = {}
    admin = user.is_admin_role
    open_req = req.status not in (LeaveRequest.REJECTED, LeaveRequest.CANCELLED)
    can_faculty_edit = (not admin and req.faculty_id == user.pk and
                        req.status in (LeaveRequest.DRAFT, LeaveRequest.AWAITING_CONSENT, LeaveRequest.AWAITING_ADMIN))
    rows = []
    adjs = (req.adjustments.filter(kind=Adjustment.LEAVE).exclude(status=Adjustment.CANCELLED)
            .select_related("school_class", "original_subject", "substitute", "subject_taught"))
    for a in adjs:
        taken = AttendanceSession.objects.filter(school_class=a.school_class, date=a.date, period_no=a.period_no).exists()
        editable = open_req and not taken and (admin or can_faculty_edit)
        row = {"adj": a, "taken": taken, "editable": editable}
        if editable:
            ctx = ctx_cache.setdefault(a.date, svc.DayContext(a.date))
            elig = svc.eligible_faculty(a.school_class, a.original_subject, a.date, a.period_no,
                                        original_faculty=a.original_faculty, ctx=ctx, ignore_adjustment_id=a.pk)
            if a.substitute and a.substitute.pk not in {f.pk for f in elig}:
                elig.append(a.substitute)
            row["eligible"] = elig
            row["subjects"] = [s for s in a.school_class.subjects.all() if s.pk != a.original_subject_id]
        rows.append(row)
    return rows


@login_required
def leave_detail(request, pk):
    req = get_object_or_404(LeaveRequest.objects.select_related("faculty", "leave_type", "created_by"), pk=pk)
    _own_or_admin(request.user, req)
    admin = request.user.is_admin_role
    rows = _rows(req, request.user)
    returns = (req.adjustments.filter(kind=Adjustment.RETURN).exclude(status=Adjustment.CANCELLED)
               .select_related("school_class", "original_subject", "original_faculty", "subject_taught"))
    live = [r for r in rows]
    complete = all(r["adj"].complete for r in live)
    return render(request, "leaves/detail.html", {
        "req": req, "rows": rows, "returns": returns, "admin": admin, "days": req.days.all(),
        "all_complete": complete, "warning": svc.balance_warning(req),
        "can_submit": (not admin and req.faculty_id == request.user.pk and req.status == LeaveRequest.DRAFT),
        "can_cancel": req.status not in (LeaveRequest.REJECTED, LeaveRequest.CANCELLED) and (
            admin or (req.faculty_id == request.user.pk and req.status != LeaveRequest.APPROVED)),
        "can_offer_return": req.status in LeaveRequest.SUBMITTED and (admin or req.faculty_id == request.user.pk),
        "can_decide": admin and req.status == LeaveRequest.AWAITING_ADMIN,
        "any_editable": any(r["editable"] for r in rows)})


@login_required
@require_POST
def leave_adjust(request, pk):
    """Save the substitute/subject chosen for each period (and optionally submit the request)."""
    req = get_object_or_404(LeaveRequest, pk=pk)
    _own_or_admin(request.user, req)
    ctx_cache, saved, problems = {}, 0, []
    adjs = req.adjustments.filter(kind=Adjustment.LEAVE).exclude(status=Adjustment.CANCELLED).select_related(
        "school_class", "original_subject", "original_faculty", "substitute", "subject_taught", "leave_request")
    for a in adjs:
        sub_id = request.POST.get(f"sub_{a.pk}", "")
        if not sub_id:
            continue
        mode = request.POST.get(f"mode_{a.pk}", "same")
        subj_id = request.POST.get(f"subj_{a.pk}", "")
        try:
            sub = User.objects.get(pk=int(sub_id), role=User.FACULTY) if sub_id.isdigit() else None
        except User.DoesNotExist:
            sub = None
        subject = Subject.objects.filter(pk=int(subj_id)).first() if subj_id.isdigit() else None
        wanted_taught = a.original_subject_id if mode == "same" else (subject.pk if subject else None)
        if a.substitute_id == (sub.pk if sub else None) and a.subject_taught_id == wanted_taught:
            continue                                   # nothing changed for this period
        try:
            svc.set_adjustment(a, user=request.user, substitute=sub, same_subject=(mode == "same"),
                               subject=subject, ctx_cache=ctx_cache)
            saved += 1
        except svc.LeaveError as exc:
            problems.append(str(exc))
    for p in problems:
        messages.error(request, p)
    if request.POST.get("action") == "submit" and not request.user.is_admin_role:
        req.refresh_from_db()
        try:
            svc.submit_request(req, user=request.user)
        except svc.LeaveError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Request submitted. Each substitute will be asked to accept.")
    elif saved and not problems:
        messages.success(request, f"Saved {saved} change(s).")
    return redirect("leave_detail", req.pk)


@admin_required
@require_POST
def adjustment_clear(request, pk):
    adj = get_object_or_404(Adjustment, pk=pk)
    try:
        svc.clear_adjustment(adj, user=request.user)
        messages.success(request, "Adjustment cancelled.")
    except svc.LeaveError as exc:
        messages.error(request, str(exc))
    return redirect("leave_detail", adj.leave_request_id)


@login_required
@require_POST
def leave_cancel(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk)
    _own_or_admin(request.user, req)
    try:
        svc.cancel_request(req, user=request.user)
        messages.success(request, "Leave cancelled.")
    except svc.LeaveError as exc:
        messages.error(request, str(exc))
    return redirect("leave_detail", req.pk)


@admin_required
@require_POST
def leave_decide(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk)
    approve = request.POST.get("decision") == "approve"
    try:
        svc.decide(req, admin=request.user, approve=approve, note=request.POST.get("note", "").strip())
        messages.success(request, "Leave approved." if approve else "Leave rejected.")
    except svc.LeaveError as exc:
        messages.error(request, str(exc))
    return redirect("leave_detail", req.pk)


@faculty_required
@require_POST
def adjustment_respond(request, pk):
    adj = get_object_or_404(Adjustment, pk=pk)
    try:
        accept = request.POST.get("answer") == "accept"
        svc.respond(adj, user=request.user, accept=accept)
        messages.success(request, "Accepted. It will appear in your periods on that day." if accept else "Declined.")
    except svc.LeaveError as exc:
        messages.error(request, str(exc))
    return redirect("home")


@login_required
@require_POST
def notifications_clear(request):
    Notification.objects.filter(user=request.user, read=False).update(read=True)
    return redirect("home")


@login_required
def return_offer(request, pk):
    """Offer to take one of a substitute's periods on another date, in exchange for their cover."""
    req = get_object_or_404(LeaveRequest, pk=pk)
    _own_or_admin(request.user, req)
    if req.status not in LeaveRequest.SUBMITTED:
        messages.error(request, "A return can only be offered once the request is submitted.")
        return redirect("leave_detail", req.pk)
    covering = {a.substitute for a in svc.leave_adjustments(req) if a.substitute}
    chosen = next((u for u in covering if str(u.pk) == request.GET.get("who", request.POST.get("who", ""))), None)
    try:
        date = datetime.date.fromisoformat(request.GET.get("date", request.POST.get("date", "")))
    except ValueError:
        date = None
    candidates = svc.return_candidates(req, chosen, date) if chosen and date else []

    if request.method == "POST" and request.POST.get("slot") and chosen and date:
        class_id, _, period = request.POST["slot"].partition(":")
        cls = get_object_or_404(SchoolClass, pk=int(class_id))
        mode = request.POST.get("mode", "same")
        subject = Subject.objects.filter(pk=int(request.POST["subj"])).first() if request.POST.get("subj", "").isdigit() else None
        try:
            svc.offer_return(req, user=request.user, school_class=cls, date=date, period_no=int(period),
                             same_subject=(mode == "same"), subject=subject)
        except svc.LeaveError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Return offered." + ("" if request.user.is_admin_role
                                                           else f" {chosen.full_name} will be asked to accept."))
            return redirect("leave_detail", req.pk)
    return render(request, "leaves/return.html", {
        "req": req, "covering": sorted(covering, key=lambda u: u.full_name), "chosen": chosen, "date": date,
        "candidates": [(c, e, [s for s in c.subjects.all() if s.pk != e.subject_id]) for c, e in candidates],
        "today": today()})


# ------------------------------------------------------------------ admin

@admin_required
def leave_list(request):
    status = request.GET.get("status", "")
    qs = LeaveRequest.objects.select_related("faculty", "leave_type")
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(status=LeaveRequest.DRAFT)
    return render(request, "leaves/list.html", {
        "requests": qs, "status": status, "statuses": LeaveRequest.STATUS_CHOICES,
        "waiting": LeaveRequest.objects.filter(status=LeaveRequest.AWAITING_ADMIN).count()})


@admin_required
def unadjusted(request):
    return render(request, "leaves/unadjusted.html", {"items": svc.unadjusted_periods(), "today": today()})


@admin_required
def balances(request):
    try:
        year = int(request.GET.get("year", today().year))
    except ValueError:
        year = today().year
    types = LeaveType.objects.filter(active=True)
    rows = [(f, svc.leave_balance(f, year)) for f in User.objects.filter(role=User.FACULTY, is_active=True)]
    return render(request, "leaves/balances.html", {"rows": rows, "types": types, "year": year})


@admin_required
def leave_type_list(request):
    return render(request, "leaves/types.html", {"types": LeaveType.objects.all()})


@admin_required
def leave_type_edit(request, pk=None):
    obj = get_object_or_404(LeaveType, pk=pk) if pk else None
    form = LeaveTypeForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("leave_type_list")
    return render(request, "form.html", {"title": "Edit leave type" if obj else "Add leave type", "form": form,
                                         "cancel": "leave_type_list"})


@admin_required
def leave_type_delete(request, pk):
    obj = get_object_or_404(LeaveType, pk=pk)
    if request.method == "POST":
        try:
            obj.delete()
            messages.success(request, "Deleted.")
        except ProtectedError:
            messages.error(request, "Leave has been recorded under this type. Untick 'Active' instead.")
        return redirect("leave_type_list")
    return render(request, "confirm_delete.html", {"obj": obj, "detail": "Types already used cannot be deleted."})
