from django import forms
from django.contrib.auth import password_validation

from .models import User


class FacultyCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, help_text="At least 6 characters.")

    class Meta:
        model = User
        fields = ["full_name", "username"]
        labels = {"username": "User ID"}
        help_texts = {"username": "Used to log in. Letters, digits and @/./+/-/_ only."}

    def clean_password(self):
        pw = self.cleaned_data["password"]
        password_validation.validate_password(pw)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.FACULTY
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class FacultyEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name"]


class ResetPasswordForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput, label="New password")
    force_change = forms.BooleanField(required=False, initial=True,
                                      label="Ask the faculty to change it at next login")

    def clean_new_password(self):
        pw = self.cleaned_data["new_password"]
        password_validation.validate_password(pw)
        return pw


class FacultyUploadForm(forms.Form):
    file = forms.FileField(label="Excel or CSV file", help_text="Columns: full_name, user_id, password (optional)")
