from django import forms

from academics.forms import DateInput
from .models import Timetable


class UploadForm(forms.Form):
    effective_from = forms.DateField(widget=DateInput(), label="Effective from",
                                     help_text="The timetable applies from this date onward. Earlier dates keep the old one.")
    file = forms.FileField(label="Excel or CSV file")


class NewVersionForm(forms.Form):
    effective_from = forms.DateField(widget=DateInput(), label="Effective from")
    copy_from = forms.ModelChoiceField(queryset=Timetable.objects.none(), required=False,
                                       empty_label="Start with an empty timetable", label="Copy from")

    def __init__(self, *args, school_class, **kwargs):
        super().__init__(*args, **kwargs)
        self.school_class = school_class
        self.fields["copy_from"].queryset = school_class.timetables.all()

    def clean_effective_from(self):
        d = self.cleaned_data["effective_from"]
        if self.school_class.timetables.filter(effective_from=d).exists():
            raise forms.ValidationError("A timetable version already exists from this date.")
        return d
