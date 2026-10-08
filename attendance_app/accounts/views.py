from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import admin_required
from .forms import FacultyCreateForm, FacultyEditForm, ResetPasswordForm
from .models import User


class AppLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        messages.success(request, "Password changed.")
        return redirect("home")
    return render(request, "form.html", {
        "title": "Change password", "form": form, "submit": "Change password",
        "forced": request.user.must_change_password,
        "cancel": None if request.user.must_change_password else "home",
    })


@admin_required
def faculty_list(request):
    return render(request, "accounts/faculty_list.html",
                  {"faculty": User.objects.filter(role=User.FACULTY).order_by("full_name")})


@admin_required
def faculty_add(request):
    form = FacultyCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Faculty account created.")
        return redirect("faculty_list")
    return render(request, "form.html", {"title": "Add faculty", "form": form, "cancel": "faculty_list"})


@admin_required
def faculty_edit(request, pk):
    user = get_object_or_404(User, pk=pk, role=User.FACULTY)
    form = FacultyEditForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("faculty_list")
    return render(request, "form.html", {"title": f"Edit {user.full_name}", "form": form, "cancel": "faculty_list"})


@admin_required
def faculty_reset_password(request, pk):
    user = get_object_or_404(User, pk=pk, role=User.FACULTY)
    form = ResetPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user.set_password(form.cleaned_data["new_password"])
        user.must_change_password = form.cleaned_data["force_change"]
        user.save()
        messages.success(request, f"Password reset for {user.full_name}.")
        return redirect("faculty_list")
    return render(request, "form.html", {"title": f"Reset password: {user.full_name}", "form": form,
                                         "submit": "Reset password", "cancel": "faculty_list"})


@admin_required
@require_POST
def faculty_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk, role=User.FACULTY)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    messages.success(request, f"{user.full_name} {'activated' if user.is_active else 'deactivated'}.")
    return redirect("faculty_list")
