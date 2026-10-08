from django.conf import settings
from django.db import models


class AttendanceSession(models.Model):
    """Attendance for one class in one period of one date. Unique per (class, date, period)."""
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="attendance_sessions")
    date = models.DateField()
    period_no = models.PositiveSmallIntegerField()
    # What was actually taught - percentages and logs are counted under this subject.
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="attendance_sessions")
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attendance_taken")
    # What the timetable said, kept so later timetable edits never change history.
    scheduled_subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="+")
    scheduled_faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # Set when this period was taken by a substitute (leave or return adjustment).
    adjustment = models.ForeignKey("leaves.Adjustment", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="sessions")
    topic = models.CharField(max_length=250)
    remarks = models.TextField(blank=True)
    unlocked = models.BooleanField(default=False, help_text="Admin has re-opened this record for the faculty")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "period_no"]
        constraints = [models.UniqueConstraint(fields=["school_class", "date", "period_no"],
                                               name="unique_attendance_per_period")]

    def __str__(self):
        return f"{self.school_class.name} {self.date} P{self.period_no}"


class AttendanceRecord(models.Model):
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey("academics.Student", on_delete=models.PROTECT, related_name="attendance_records")
    present = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "student"], name="unique_record_per_student")]


class AttendanceAudit(models.Model):
    """Who changed an attendance record after it was first saved."""
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name="audits")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)
    summary = models.TextField()

    class Meta:
        ordering = ["-at"]
