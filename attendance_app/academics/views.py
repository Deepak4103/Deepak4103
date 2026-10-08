from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from accounts.models import User

from . import importing
from .forms import ClassForm, HolidayForm, StudentForm, StudentUploadForm, SubjectForm
from .models import Allotment, Holiday, SchoolClass, Student, Subject

STUDENT_HEADERS = ["roll_no", "name"]
STUDENT_EXAMPLE = [["21CSE001", "Asha Rao"], ["21CSE002", "Ravi Kumar"]]


def _form_page(request, form, title, back, **extra):
    return render(request, "form.html", {"title": title, "form": form, "cancel": back, **extra})


def _delete_page(request, obj, back_url_name, back_args=(), detail=""):
    if request.method == "POST":
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, "Cannot delete: a timetable or attendance records are linked to it.")
        else:
            messages.success(request, "Deleted.")
        return redirect(back_url_name, *back_args)
    return render(request, "confirm_delete.html", {"obj": obj, "detail": detail,
                                                   "back": back_url_name, "back_args": back_args})


# ---------- home ----------

@admin_required
def admin_home(request):
    stats = [
        ("Classes", SchoolClass.objects.count(), "class_list"),
        ("Students", Student.objects.count(), "class_list"),
        ("Faculty", User.objects.filter(role=User.FACULTY, is_active=True).count(), "faculty_list"),
        ("Holidays", Holiday.objects.count(), "holiday_list"),
    ]
    from attendance import services as att
    today = att.today()
    index = att.ScheduleIndex(today, today)
    slots = index.slots(today)
    summary = {"done": sum(1 for s in slots if s.completed), "pending": sum(1 for s in slots if not s.completed)}
    return render(request, "academics/admin_home.html", {"stats": stats, "summary": summary, "today": today})


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect("admin_home" if request.user.is_admin_role else "faculty_home")


# ---------- classes ----------

@admin_required
def class_list(request):
    return render(request, "academics/class_list.html", {"classes": SchoolClass.objects.all()})


@admin_required
def class_add(request):
    form = ClassForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save()
        messages.success(request, "Class created. Now add subjects and students.")
        return redirect("class_detail", c.pk)
    return _form_page(request, form, "Add class", "class_list")


@admin_required
def class_detail(request, pk):
    c = get_object_or_404(SchoolClass, pk=pk)
    return render(request, "academics/class_detail.html", {
        "c": c, "students": c.students.all(),
        "subjects": c.subjects.select_related("allotment__faculty"),
    })


@admin_required
def class_edit(request, pk):
    c = get_object_or_404(SchoolClass, pk=pk)
    form = ClassForm(request.POST or None, instance=c)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("class_detail", c.pk)
    return _form_page(request, form, f"Edit {c.name}", "class_detail", cancel_args=[c.pk])


@admin_required
def class_delete(request, pk):
    c = get_object_or_404(SchoolClass, pk=pk)
    detail = f"This also deletes its {c.students.count()} students and {c.subjects.count()} subjects."
    return _delete_page(request, c, "class_list", detail=detail)


# ---------- students ----------

@admin_required
def student_add(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    form = StudentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.school_class = c
        s.save()
        messages.success(request, f"Added {s.roll_no}. Add another below.")
        return redirect("student_add", c.pk)
    return _form_page(request, form, f"Add student to {c.name}", "class_detail", cancel_args=[c.pk],
                      submit="Add student")


@admin_required
def student_edit(request, pk):
    s = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST or None, instance=s)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("class_detail", s.school_class_id)
    return _form_page(request, form, f"Edit {s.roll_no}", "class_detail", cancel_args=[s.school_class_id])


@admin_required
def student_delete(request, pk):
    s = get_object_or_404(Student, pk=pk)
    return _delete_page(request, s, "class_detail", (s.school_class_id,))


def validate_student_rows(rows):
    """Split uploaded rows into (valid, errors). Roll numbers must be unique in the file and the database."""
    valid, errors, seen = [], [], set()
    existing = {s.roll_no: s.school_class.name for s in Student.objects.select_related("school_class")}
    for r in rows:
        roll = (r.get("roll_no") or r.get("roll") or r.get("rollno") or "").strip().upper()
        name = (r.get("name") or "").strip()
        line = r["_line"]
        if not roll or not name:
            errors.append((line, roll, name, "Roll number and name are both required"))
        elif roll in seen:
            errors.append((line, roll, name, "Duplicate roll number in this file"))
        elif roll in existing:
            errors.append((line, roll, name, f"Roll number already exists (class: {existing[roll]})"))
        else:
            seen.add(roll)
            valid.append({"roll_no": roll, "name": name})
    return valid, errors


@admin_required
def student_upload(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    session_key = f"student_upload_{c.pk}"
    if request.method == "POST" and request.POST.get("action") == "confirm":
        valid = request.session.pop(session_key, None)
        if not valid:
            messages.error(request, "Upload expired. Please upload the file again.")
            return redirect("student_upload", c.pk)
        valid, _ = validate_student_rows([{"_line": i, **v} for i, v in enumerate(valid)])  # re-check
        with transaction.atomic():
            Student.objects.bulk_create([Student(school_class=c, **v) for v in valid])
        messages.success(request, f"{len(valid)} students added.")
        return redirect("class_detail", c.pk)

    form = StudentUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            headers, rows = importing.read_rows(form.cleaned_data["file"])
        except importing.UploadError as exc:
            form.add_error("file", str(exc))
        else:
            if not ({"roll_no", "roll", "rollno"} & set(headers)) or "name" not in headers:
                form.add_error("file", "Header row must contain: roll_no, name")
            else:
                valid, errors = validate_student_rows(rows)
                request.session[session_key] = valid
                return render(request, "academics/student_preview.html",
                              {"c": c, "valid": valid, "errors": errors})
    return render(request, "academics/student_upload.html", {"c": c, "form": form})


@admin_required
def student_template(request, fmt):
    if fmt == "xlsx":
        resp = HttpResponse(importing.template_xlsx(STUDENT_HEADERS, STUDENT_EXAMPLE),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        resp = HttpResponse(importing.template_csv(STUDENT_HEADERS, STUDENT_EXAMPLE), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="students_template.{fmt}"'
    return resp


# ---------- subjects & allotment ----------

@admin_required
def subject_add(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    form = SubjectForm(request.POST or None, school_class=c)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.school_class = c
        s.save()
        messages.success(request, f"Added {s.name}. Add another below.")
        return redirect("subject_add", c.pk)
    return _form_page(request, form, f"Add subject to {c.name}", "class_detail", cancel_args=[c.pk],
                      submit="Add subject")


@admin_required
def subject_edit(request, pk):
    s = get_object_or_404(Subject, pk=pk)
    form = SubjectForm(request.POST or None, instance=s)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("class_detail", s.school_class_id)
    return _form_page(request, form, f"Edit {s.name}", "class_detail", cancel_args=[s.school_class_id])


@admin_required
def subject_delete(request, pk):
    s = get_object_or_404(Subject, pk=pk)
    return _delete_page(request, s, "class_detail", (s.school_class_id,))


@admin_required
def allotment(request, class_pk):
    c = get_object_or_404(SchoolClass, pk=class_pk)
    subjects = list(c.subjects.select_related("allotment"))
    faculty = User.objects.filter(role=User.FACULTY, is_active=True)
    if request.method == "POST":
        valid_ids = {str(f.pk) for f in faculty}
        with transaction.atomic():
            for s in subjects:
                val = request.POST.get(f"subject_{s.pk}", "")
                if val in valid_ids:
                    Allotment.objects.update_or_create(subject=s, defaults={"faculty_id": int(val)})
                elif val == "":
                    Allotment.objects.filter(subject=s).delete()
        messages.success(request, "Allotment saved.")
        return redirect("class_detail", c.pk)
    rows = [(s, getattr(s, "allotment", None)) for s in subjects]
    return render(request, "academics/allotment.html", {"c": c, "rows": rows, "faculty": faculty})


# ---------- holidays ----------

@admin_required
def holiday_list(request):
    return render(request, "academics/holiday_list.html",
                  {"holidays": Holiday.objects.select_related("school_class")})


@admin_required
def holiday_add(request):
    form = HolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Holiday added.")
        return redirect("holiday_list")
    return _form_page(request, form, "Add holiday", "holiday_list")


@admin_required
def holiday_edit(request, pk):
    h = get_object_or_404(Holiday, pk=pk)
    form = HolidayForm(request.POST or None, instance=h)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("holiday_list")
    return _form_page(request, form, "Edit holiday", "holiday_list")


@admin_required
def holiday_delete(request, pk):
    return _delete_page(request, get_object_or_404(Holiday, pk=pk), "holiday_list")
