from django.conf import settings
from django.db import models

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
DAY_CHOICES = list(enumerate(DAY_NAMES))


class Timetable(models.Model):
    """One version of a class's weekly timetable, in force from `effective_from` until the next version."""
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="timetables")
    effective_from = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["school_class", "-effective_from"]
        constraints = [models.UniqueConstraint(fields=["school_class", "effective_from"],
                                               name="unique_timetable_version")]

    def __str__(self):
        return f"{self.school_class.name} from {self.effective_from}"


class TimetableEntry(models.Model):
    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE, related_name="entries")
    day = models.PositiveSmallIntegerField(choices=DAY_CHOICES)  # 0 = Monday
    period_no = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="timetable_entries")
    faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="timetable_entries")

    class Meta:
        ordering = ["day", "period_no"]
        constraints = [models.UniqueConstraint(fields=["timetable", "day", "period_no"],
                                               name="unique_slot_per_timetable")]

    def __str__(self):
        return f"{DAY_NAMES[self.day]} P{self.period_no}: {self.subject.code}"
