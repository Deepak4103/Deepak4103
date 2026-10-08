from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from .periods import SCOPE_CHOICES, covered_periods


class LeaveType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    days_per_year = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("12.0"),
                                        help_text="Days allowed per calendar year")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    DRAFT, AWAITING_CONSENT, AWAITING_ADMIN = "draft", "awaiting_consent", "awaiting_admin"
    APPROVED, REJECTED, CANCELLED = "approved", "rejected", "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "Adjustments being filled in"), (AWAITING_CONSENT, "Waiting for substitutes"),
        (AWAITING_ADMIN, "Waiting for admin approval"), (APPROVED, "Approved"),
        (REJECTED, "Rejected"), (CANCELLED, "Cancelled")]
    SUBMITTED = (AWAITING_CONSENT, AWAITING_ADMIN, APPROVED)   # states in which the faculty counts as on leave

    faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    from_date = models.DateField()
    to_date = models.DateField()
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    periods = models.CharField(max_length=40, blank=True, help_text="Comma separated, for 'specific periods'")
    reason = models.CharField(max_length=250, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-from_date", "-id"]

    @property
    def entered_by_admin(self):
        return self.created_by.role == "admin" and self.created_by_id != self.faculty_id

    @property
    def total_days(self):
        return sum((d.days_value for d in self.days.all()), Decimal("0"))

    def covers(self, period_no, forenoon_last):
        return period_no in covered_periods(self.scope, self.periods, forenoon_last)

    def __str__(self):
        return f"{self.faculty} {self.leave_type} {self.from_date}..{self.to_date}"


class LeaveDay(models.Model):
    request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="days")
    date = models.DateField()
    days_value = models.DecimalField(max_digits=3, decimal_places=1)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["request", "date"], name="unique_leave_day")]


class Adjustment(models.Model):
    """Who takes one period instead of its timetable faculty.

    LEAVE: `original_faculty` is on leave, `substitute` covers.
    RETURN: the leave applicant (`substitute`) takes a period of the person who covered for them (`original_faculty`).
    """
    LEAVE, RETURN = "leave", "return"
    UNASSIGNED, PENDING, ACCEPTED, DECLINED, CANCELLED = "unassigned", "pending", "accepted", "declined", "cancelled"
    STATUS_CHOICES = [(UNASSIGNED, "No substitute yet"), (PENDING, "Waiting for acceptance"), (ACCEPTED, "Accepted"),
                      (DECLINED, "Declined"), (CANCELLED, "Cancelled")]

    kind = models.CharField(max_length=10, default=LEAVE, choices=[(LEAVE, "Leave"), (RETURN, "Return")])
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="adjustments")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="adjustments")
    date = models.DateField()
    period_no = models.PositiveSmallIntegerField()
    original_faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    original_subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="+")
    substitute = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="adjustments_taken")
    subject_taught = models.ForeignKey("academics.Subject", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=UNASSIGNED)
    made_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    made_by_role = models.CharField(max_length=10, blank=True)       # "faculty" or "admin"
    consent_required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "period_no"]
        constraints = [models.UniqueConstraint(
            fields=["school_class", "date", "period_no"], condition=~Q(status="cancelled"),
            name="one_live_adjustment_per_period")]

    @property
    def complete(self):
        return bool(self.substitute_id and self.subject_taught_id)

    @property
    def same_subject(self):
        return self.subject_taught_id is not None and self.subject_taught_id == self.original_subject_id

    @property
    def responder_id(self):
        """The person who must accept or decline this adjustment."""
        return self.original_faculty_id if self.kind == self.RETURN else self.substitute_id

    def __str__(self):
        return f"{self.school_class} {self.date} P{self.period_no}"


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    text = models.CharField(max_length=300)
    url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
