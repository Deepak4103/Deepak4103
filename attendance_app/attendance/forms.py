from django import forms


class AttendanceForm(forms.Form):
    topic = forms.CharField(max_length=250, label="Topic covered",
                            error_messages={"required": "The topic covered in this period is required."},
                            widget=forms.TextInput(attrs={"placeholder": "e.g. Binary search trees"}))
    remarks = forms.CharField(required=False, label="Remarks (optional)", widget=forms.Textarea(attrs={"rows": 2}))

    def clean_topic(self):
        topic = self.cleaned_data["topic"].strip()
        if not topic:
            raise forms.ValidationError("The topic covered in this period is required.")
        return topic
