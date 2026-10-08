import datetime

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from academics import importing
from academics.models import SchoolClass
from accounts.decorators import admin_required
from accounts.models import User

from . import services as svc
from .forms import NewVersionForm, UploadForm
from .models import DAY_NAMES, Timetable


@admin_required
def timetable_list(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    current = svc.timetable_in_force(c, timezone.localdate())
    return render(request, "timetable/list.html",
                  {"c": c, "versions": c.timetables.all(), "current": current,
                   "today": timezone.localdate()})


@admin_required
def template_download(request, fmt):
    if fmt == "xlsx":
        resp = HttpResponse(importing.template_xlsx(svc.HEADERS),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        resp = HttpResponse(importing.template_csv(svc.HEADERS), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="timetable_template.{fmt}"'
    return resp


@admin_required
def timetable_upload(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    key = f"timetable_upload_{c.pk}"

    if request.method == "POST" and request.POST.get("action") == "confirm":
        data = request.session.pop(key, None)
        if not data:
            messages.error(request, "Upload expired. Please upload the file again.")
            return redirect("timetable_upload", c.pk)
        eff = datetime.date.fromisoformat(data["effective_from"])
        errors = svc.validate_entries(c, eff, data["cleaned"])
        if errors or c.timetables.filter(effective_from=eff).exists():
            messages.error(request, "The timetable could not be saved: " + " ".join(errors or ["Version exists."]))
            return redirect("timetable_upload", c.pk)
        with transaction.atomic():
            tt = Timetable.objects.create(school_class=c, effective_from=eff)
            svc.save_entries(tt, data["cleaned"])
        messages.success(request, "Timetable saved. You can fine-tune it in the weekly grid.")
        return redirect("timetable_grid", tt.pk)

    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        eff = form.cleaned_data["effective_from"]
        try:
            headers, rows = importing.read_rows(form.cleaned_data["file"])
        except importing.UploadError as exc:
            form.add_error("file", str(exc))
        else:
            missing = {"day", "subject", "faculty"} - set(headers)
            if missing or not ({"period", "period_no"} & set(headers)):
                form.add_error("file", "Header row must be: " + ", ".join(svc.HEADERS))
            elif c.timetables.filter(effective_from=eff).exists():
                form.add_error("effective_from", "A timetable version already exists from this date. "
                                                 "Edit it, or choose another date.")
            else:
                cleaned, row_errors = svc.parse_upload_rows(c, rows)
                rule_errors = svc.validate_entries(c, eff, cleaned)
                can_save = not row_errors and not rule_errors and bool(cleaned)
                if can_save:
                    request.session[key] = {"effective_from": eff.isoformat(), "cleaned": cleaned}
                return render(request, "timetable/preview.html", {
                    "c": c, "effective_from": eff, "grid": svc.build_grid(cleaned), "days": DAY_NAMES[:6],
                    "row_errors": row_errors, "rule_errors": rule_errors, "can_save": can_save,
                    "count": len(cleaned)})
    return render(request, "timetable/upload.html", {
        "c": c, "form": form, "subjects": c.subjects.all(),
        "faculty": User.objects.filter(role=User.FACULTY, is_active=True)})


@admin_required
def timetable_new(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    form = NewVersionForm(request.POST or None, school_class=c)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            tt = Timetable.objects.create(school_class=c, effective_from=form.cleaned_data["effective_from"])
            src = form.cleaned_data["copy_from"]
            if src:
                svc.save_entries(tt, svc.entries_to_cleaned(src))
        return redirect("timetable_grid", tt.pk)
    return render(request, "form.html", {"title": f"New timetable version: {c.name}", "form": form,
                                         "cancel": "timetable_list", "cancel_args": [c.pk], "submit": "Create"})


def _posted_cleaned(post, subjects_by_id, allotted):
    """Read the grid form into cleaned entries. Returns (cleaned, errors, period_times)."""
    cleaned, errors = [], []
    period_times = {p: (post.get(f"start_{p}", "").strip(), post.get(f"end_{p}", "").strip()) for p in svc.PERIODS}
    for d in svc.DAYS:
        for p in svc.PERIODS:
            sid = post.get(f"s_{d}_{p}", "")
            if not sid:
                continue
            where = f"{DAY_NAMES[d]} period {p}"
            if not sid.isdigit() or int(sid) not in subjects_by_id:
                errors.append(f"{where}: invalid subject.")
                continue
            fid = post.get(f"f_{d}_{p}", "") or str(allotted.get(int(sid), ""))
            if not fid.isdigit():
                errors.append(f"{where}: choose a faculty member.")
                continue
            start, end = period_times[p]
            try:
                svc.parse_time(start)
                svc.parse_time(end)
            except ValueError:
                errors.append(f"Period {p}: enter valid start and end times.")
                continue
            cleaned.append({"day": d, "period": p, "start": svc.fmt_time(svc.parse_time(start)),
                            "end": svc.fmt_time(svc.parse_time(end)), "subject_id": int(sid), "faculty_id": int(fid)})
    return cleaned, list(dict.fromkeys(errors)), period_times


@admin_required
def timetable_grid(request, pk):
    tt = get_object_or_404(Timetable.objects.select_related("school_class"), pk=pk)
    c = tt.school_class
    subjects = list(c.subjects.select_related("allotment"))
    subjects_by_id = {s.pk: s for s in subjects}
    allotted = {s.pk: s.allotment.faculty_id for s in subjects if hasattr(s, "allotment")}
    faculty = list(User.objects.filter(role=User.FACULTY, is_active=True))
    errors = []

    if request.method == "POST":
        cleaned, errors, period_times = _posted_cleaned(request.POST, subjects_by_id, allotted)
        eff_text = request.POST.get("effective_from", "")
        try:
            eff = datetime.date.fromisoformat(eff_text)
        except ValueError:
            eff = None
            errors.append("Enter a valid effective-from date.")
        if eff and c.timetables.filter(effective_from=eff).exclude(pk=tt.pk).exists():
            errors.append("Another version already starts on that date.")
        if not errors:
            errors = svc.validate_entries(c, eff, cleaned, exclude_timetable_id=tt.pk)
        if not errors:
            with transaction.atomic():
                tt.effective_from = eff
                tt.save(update_fields=["effective_from"])
                svc.save_entries(tt, cleaned)
            messages.success(request, "Timetable saved.")
            return redirect("timetable_list", c.pk)
        posted = {(e["day"], e["period"]): e for e in cleaned}
        for d in svc.DAYS:      # keep the user's picks on re-display even when invalid
            for p in svc.PERIODS:
                sid, fid = request.POST.get(f"s_{d}_{p}", ""), request.POST.get(f"f_{d}_{p}", "")
                if sid.isdigit() and (d, p) not in posted:
                    posted[(d, p)] = {"subject_id": int(sid), "faculty_id": int(fid) if fid.isdigit() else None}
        effective_value = eff_text
    else:
        posted = {(e["day"], e["period"]): e for e in svc.entries_to_cleaned(tt)}
        period_times = {}
        for e in posted.values():
            period_times.setdefault(e["period"], (e["start"], e["end"]))
        effective_value = tt.effective_from.isoformat()

    default_times = ["09:00-09:50", "09:50-10:40", "10:50-11:40", "11:40-12:30",
                     "13:30-14:20", "14:20-15:10", "15:10-16:00"]
    periods = []
    for p in svc.PERIODS:
        start, end = period_times.get(p) or tuple(default_times[p - 1].split("-"))
        periods.append({"no": p, "start": start, "end": end})
    day_cards = []
    for d in svc.DAYS:
        cells = []
        for p in svc.PERIODS:
            e = posted.get((d, p)) or {}
            cells.append({"period": p, "subject_id": e.get("subject_id"), "faculty_id": e.get("faculty_id"),
                          "s_name": f"s_{d}_{p}", "f_name": f"f_{d}_{p}"})
        day_cards.append({"name": DAY_NAMES[d], "cells": cells})
    return render(request, "timetable/grid.html", {
        "tt": tt, "c": c, "subjects": subjects, "faculty": faculty, "allotted": allotted, "periods": periods,
        "day_cards": day_cards, "errors": errors, "effective_value": effective_value})


@admin_required
def timetable_delete(request, pk):
    tt = get_object_or_404(Timetable, pk=pk)
    cid = tt.school_class_id
    if request.method == "POST":
        tt.delete()
        messages.success(request, "Timetable version deleted.")
        return redirect("timetable_list", cid)
    return render(request, "confirm_delete.html", {
        "obj": tt, "detail": "Attendance already entered is not affected."})
