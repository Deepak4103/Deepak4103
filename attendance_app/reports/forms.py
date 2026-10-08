from django import forms

from academics.forms import DateInput
from academics.models import SchoolClass, Subject
from accounts.models import User

from .stats import Filters


class ReportFilterForm(forms.Form):
    school_class = forms.ModelChoiceField(queryset=SchoolClass.objects.all(), required=False, label="Class")
    subject = forms.ChoiceField(required=False, label="Subject")
    faculty = forms.ModelChoiceField(queryset=User.objects.filter(role=User.FACULTY), required=False, label="Faculty")
    date = forms.DateField(required=False, widget=DateInput(), label="Date")
    date_from = forms.DateField(required=False, widget=DateInput(), label="From date")
    date_to = forms.DateField(required=False, widget=DateInput(), label="To date")
    threshold = forms.IntegerField(required=False, min_value=1, max_value=100, label="Threshold %")

    def __init__(self, *args, fields, needs_class=False, **kwargs):
        super().__init__(*args, **kwargs)
        codes = {}
        for s in Subject.objects.all():
            codes.setdefault(s.code.upper(), s.name)
        self.fields["subject"].choices = [("", "All subjects")] + [(c, f"{n} ({c})") for c, n in sorted(codes.items())]
        for name in list(self.fields):
            if name not in fields:
                del self.fields[name]
        if needs_class:
            self.fields["school_class"].required = True
            self.fields["school_class"].empty_label = None

    def clean(self):
        d = super().clean()
        if d.get("date_from") and d.get("date_to") and d["date_to"] < d["date_from"]:
            self.add_error("date_to", "The end date cannot be before the start date.")
        return d

    def filters(self):
        d = self.cleaned_data
        return Filters(school_class=d.get("school_class"), subject_code=d.get("subject") or "",
                       faculty=d.get("faculty"), date_from=d.get("date_from"), date_to=d.get("date_to"),
                       date=d.get("date"), threshold=d.get("threshold"))
