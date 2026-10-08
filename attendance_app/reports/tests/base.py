import datetime
from decimal import Decimal

from academics.models import Student
from attendance import services as att
from attendance.tests.base import MON, AttendanceTestCase
from leaves.models import Adjustment, LeaveDay, LeaveRequest, LeaveType


def week(n):
    """The Monday n weeks after MON."""
    return MON + datetime.timedelta(days=7 * n)


class ReportTestCase(AttendanceTestCase):
    """Class A: students R1..R4. DS (Ravi) is Mon P1, DB (Sneha) is Mon P2. Helpers add entered periods."""

    def setUp(self):
        super().setUp()
        self.set_today(week(12))
        self.lt = LeaveType.objects.create(name="Casual", days_per_year=Decimal("12.0"))

    def set_today(self, date):
        super().set_today(date)
        from unittest import mock
        p = mock.patch("leaves.services.today", return_value=date)
        p.start()
        self.addCleanup(p.stop)

    def held(self, date, period=1, absent=(), topic="Topic", user=None, adjustment=None):
        entry = self.e1 if period == 1 else self.e2
        return att.save_attendance(school_class=self.c, date=date, period_no=period, entry=entry,
                                   user=user or self.admin, absent_ids={s.pk for s in absent}, topic=topic,
                                   adjustment=adjustment)

    def adjusted(self, date, taught=None, substitute=None, same=False, absent=(), status=Adjustment.ACCEPTED,
                 req_status=LeaveRequest.APPROVED, topic="Cover"):
        """Ravi's DS (P1) taken by `substitute`, teaching `taught` (default: Databases)."""
        substitute = substitute or self.sneha
        taught = self.ds if same else (taught or self.db)
        req = LeaveRequest.objects.create(faculty=self.ravi, leave_type=self.lt, from_date=date, to_date=date,
                                          scope="periods", periods="1", status=req_status, created_by=self.admin)
        LeaveDay.objects.create(request=req, date=date, days_value=Decimal("0.5"))
        adj = Adjustment.objects.create(leave_request=req, school_class=self.c, date=date, period_no=1,
                                        original_faculty=self.ravi, original_subject=self.ds, substitute=substitute,
                                        subject_taught=taught, status=status, made_by=self.admin, made_by_role="admin")
        return self.held(date, 1, absent=absent, topic=topic, user=substitute, adjustment=adj)

    def r(self, n):
        return self.students[n - 1]
