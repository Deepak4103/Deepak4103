from django import forms
from django.contrib.auth import get_user_model

from .models import Holiday, SchoolClass, Student, Subject

User = get_user_model()


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%d", **kw)


class ClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ["name", "branch", "year", "semester", "section"]


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["roll_no", "name"]

    def clean_roll_no(self):
        roll = self.cleaned_data["roll_no"].strip().upper()
        clash = Student.objects.filter(roll_no=roll).exclude(pk=self.instance.pk).first()
        if clash:
            raise forms.ValidationError(f"Roll number {roll} already exists (class: {clash.school_class.name}).")
        return roll


class StudentUploadForm(forms.Form):
    file = forms.FileField(label="Excel or CSV file", help_text="Columns: roll_no, name")


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "code"]

    def __init__(self, *args, school_class=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school_class = school_class or self.instance.school_class

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        clash = Subject.objects.filter(school_class=self.school_class, code=code).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("This class already has a subject with that code.")
        return code


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["from_date", "to_date", "reason", "school_class"]
        widgets = {"from_date": DateInput(), "to_date": DateInput()}
