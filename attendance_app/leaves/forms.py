from django import forms
from django.conf import settings

from academics.forms import DateInput
from accounts.models import User

from .models import LeaveType
from .periods import PERIODS, SCOPE_CHOICES


class LeaveApplyForm(forms.Form):
    faculty = forms.ModelChoiceField(queryset=User.objects.none(), required=False, label="Faculty")
    leave_type = forms.ModelChoiceField(queryset=LeaveType.objects.none(), label="Leave type")
    from_date = forms.DateField(widget=DateInput(), label="From date")
    to_date = forms.DateField(widget=DateInput(), label="To date")
    scope = forms.ChoiceField(choices=SCOPE_CHOICES, widget=forms.RadioSelect, initial="full", label="For")
    periods = forms.MultipleChoiceField(
        required=False, label="Which periods", widget=forms.CheckboxSelectMultiple,
        choices=[(str(p), f"P{p}") for p in range(1, settings.PERIODS_PER_DAY + 1)])
    reason = forms.CharField(required=False, max_length=250, label="Reason (optional)")

    def __init__(self, *args, admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin = admin
        self.fields["leave_type"].queryset = LeaveType.objects.filter(active=True)
        if admin:
            self.fields["faculty"].queryset = User.objects.filter(role=User.FACULTY, is_active=True)
            self.fields["faculty"].required = True
        else:
            del self.fields["faculty"]

    def clean(self):
        data = super().clean()
        if data.get("from_date") and data.get("to_date") and data["to_date"] < data["from_date"]:
            self.add_error("to_date", "The end date cannot be before the start date.")
        if data.get("scope") == PERIODS and not data.get("periods"):
            self.add_error("periods", "Choose at least one period.")
        return data


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "days_per_year", "active"]
        labels = {"days_per_year": "Days allowed per year"}
