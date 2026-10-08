import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SchoolClass(models.Model):
    name = models.CharField(max_length=100, help_text="Short name, e.g. CSE-2-A")
    branch = models.CharField(max_length=60, help_text="e.g. CSE")
    year = models.PositiveSmallIntegerField(help_text="Year of study, e.g. 2")
    semester = models.PositiveSmallIntegerField(help_text="Semester, e.g. 1")
    section = models.CharField(max_length=10, help_text="e.g. A")

    class Meta:
        ordering = ["branch", "year", "semester", "section"]
        constraints = [models.UniqueConstraint(
            fields=["branch", "year", "semester", "section"], name="unique_class_identity")]
        verbose_name_plural = "classes"

    @property
    def full_name(self):
        roman = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(self.year, str(self.year))
        return f"{self.branch} - {roman} Year - Sem {self.semester} - Section {self.section}"

    def __str__(self):
        return self.full_name


class Student(models.Model):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="students")
    roll_no = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["roll_no"]

    def save(self, *args, **kwargs):
        self.roll_no = self.roll_no.strip().upper()
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.roll_no} {self.name}"


class Subject(models.Model):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["school_class", "code"], name="unique_subject_code_per_class")]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Allotment(models.Model):
    """The faculty member who teaches a subject of a class."""
    subject = models.OneToOneField(Subject, on_delete=models.CASCADE, related_name="allotment")
    faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="allotments")

    def __str__(self):
        return f"{self.subject} -> {self.faculty}"


class Holiday(models.Model):
    """A holiday / non-working day. school_class empty = applies to every class."""
    from_date = models.DateField()
    to_date = models.DateField(help_text="Same as 'from' for a single day")
    reason = models.CharField(max_length=150)
    school_class = models.ForeignKey(SchoolClass, null=True, blank=True, on_delete=models.CASCADE,
                                     related_name="holidays", verbose_name="Only for class",
                                     help_text="Leave blank for the whole college")

    class Meta:
        ordering = ["-from_date"]

    def clean(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValidationError({"to_date": "End date cannot be before the start date."})

    def __str__(self):
        return f"{self.reason} ({self.from_date} - {self.to_date})"


def is_holiday(date: datetime.date, school_class=None) -> bool:
    """True if `date` is a Sunday or falls in a holiday (college-wide, or for the given class)."""
    if date.weekday() == 6:  # Sunday: college works Monday-Saturday
        return True
    qs = Holiday.objects.filter(from_date__lte=date, to_date__gte=date)
    if school_class is None:
        return qs.filter(school_class__isnull=True).exists()
    return qs.filter(models.Q(school_class__isnull=True) | models.Q(school_class=school_class)).exists()


class Setting(models.Model):
    """Small key/value store for admin-editable settings."""
    key = models.CharField(max_length=60, unique=True)
    value = models.CharField(max_length=200)


SETTING_DEFAULTS = {"forenoon_last_period": "4"}


def get_setting(key):
    row = Setting.objects.filter(key=key).first()
    return row.value if row else SETTING_DEFAULTS[key]


def set_setting(key, value):
    Setting.objects.update_or_create(key=key, defaults={"value": str(value)})


def forenoon_last_period():
    """Periods 1..N are the forenoon; the rest are the afternoon."""
    return int(get_setting("forenoon_last_period"))
