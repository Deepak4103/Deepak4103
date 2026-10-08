import datetime

from leaves import services as svc
from leaves.models import Adjustment, LeaveDay, LeaveRequest
from leaves.periods import FULL, PERIODS

from .base import MON, TUE, LeaveTestCase


def names(users):
    return sorted(u.username for u in users)


class EligibilityTests(LeaveTestCase):
    def eligible(self, period=1, date=MON, cls=None, subject=None, original=None):
        cls, subject = cls or self.A, subject or self.A_ds
        return svc.eligible_faculty(cls, subject, date, period, original_faculty=original or self.ravi)

    def put_on_leave(self, faculty, scope=FULL, periods="", status=LeaveRequest.APPROVED):
        req = LeaveRequest.objects.create(faculty=faculty, leave_type=self.casual, from_date=MON, to_date=MON,
                                          scope=scope, periods=periods, status=status, created_by=self.admin)
        LeaveDay.objects.create(request=req, date=MON, days_value=1)
        return req

    def test_teaches_the_same_class_or_the_same_subject_elsewhere(self):
        # Sneha teaches class A (DB); Dev teaches DS to class B. Anil teaches only Physics in B.
        self.assertEqual(names(self.eligible(period=1)), ["dev", "sneha"])

    def test_unrelated_faculty_is_never_eligible(self):
        self.assertNotIn("anil", names(self.eligible(period=4)))

    def test_original_faculty_is_excluded(self):
        self.assertNotIn("ravi", names(self.eligible()))

    def test_inactive_faculty_excluded(self):
        self.sneha.is_active = False
        self.sneha.save()
        self.assertEqual(names(self.eligible()), ["dev"])

    def test_admin_account_is_not_a_substitute(self):
        self.assertNotIn("adm", names(self.eligible()))

    def test_must_be_free_in_that_period_per_timetable(self):
        # Sneha teaches class A in period 2 and 4 -> not free then; Dev teaches B in period 2.
        self.assertEqual(names(self.eligible(period=2, subject=self.A_ds)), [])
        self.assertEqual(names(self.eligible(period=4)), ["dev"])
        self.assertEqual(names(self.eligible(period=3)), ["dev", "sneha"])

    def test_timetable_version_not_yet_in_force_does_not_make_someone_busy(self):
        from timetable.models import Timetable
        future = Timetable.objects.create(school_class=self.B, effective_from=datetime.date(2026, 12, 1))
        self.entry(future, 0, 3, self.B_ds, self.sneha)        # Sneha would be busy from December only
        self.assertIn("sneha", names(self.eligible(period=3)))
        self.assertNotIn("sneha", names(self.eligible(period=3, date=datetime.date(2026, 12, 7))))

    def test_not_free_on_other_weekdays_is_irrelevant(self):
        self.assertIn("sneha", names(self.eligible(period=1, date=TUE)))      # her periods are on Monday only

    def test_faculty_on_leave_excluded(self):
        self.put_on_leave(self.sneha)
        self.assertEqual(names(self.eligible(period=3)), ["dev"])

    def test_half_day_leave_only_blocks_those_periods(self):
        self.put_on_leave(self.sneha, scope="forenoon")       # periods 1-4 by default
        self.assertNotIn("sneha", names(self.eligible(period=3)))
        self.put_on_leave(self.dev, scope=PERIODS, periods="3")
        self.assertNotIn("dev", names(self.eligible(period=3)))
        self.assertIn("dev", names(self.eligible(period=1)))

    def test_draft_or_rejected_leave_does_not_block(self):
        self.put_on_leave(self.sneha, status=LeaveRequest.DRAFT)
        self.put_on_leave(self.sneha, status=LeaveRequest.REJECTED)
        self.assertIn("sneha", names(self.eligible(period=3)))

    def test_already_committed_to_another_substitution_is_excluded(self):
        req = self.put_on_leave(self.anil, status=LeaveRequest.AWAITING_CONSENT)
        Adjustment.objects.create(leave_request=req, school_class=self.B, date=MON, period_no=3,
                                  original_faculty=self.anil, original_subject=self.B_ph, substitute=self.sneha,
                                  subject_taught=self.B_ph, status=Adjustment.PENDING)
        self.assertNotIn("sneha", names(self.eligible(period=3)))
        self.assertIn("sneha", names(self.eligible(period=1)))

    def test_declined_or_unassigned_adjustment_does_not_hold_the_substitute(self):
        req = self.put_on_leave(self.anil, status=LeaveRequest.AWAITING_CONSENT)
        Adjustment.objects.create(leave_request=req, school_class=self.B, date=MON, period_no=3,
                                  original_faculty=self.anil, original_subject=self.B_ph, substitute=self.sneha,
                                  subject_taught=self.B_ph, status=Adjustment.DECLINED)
        self.assertIn("sneha", names(self.eligible(period=3)))

    def test_own_adjustment_is_ignored_when_rechecking(self):
        req = self.put_on_leave(self.ravi, status=LeaveRequest.AWAITING_CONSENT)
        adj = Adjustment.objects.create(leave_request=req, school_class=self.A, date=MON, period_no=3,
                                        original_faculty=self.ravi, original_subject=self.A_ds, substitute=self.sneha,
                                        subject_taught=self.A_ds, status=Adjustment.PENDING)
        without = svc.eligible_faculty(self.A, self.A_ds, MON, 3, original_faculty=self.ravi)
        self.assertNotIn("sneha", names(without))                       # she is holding it
        ok = svc.eligible_faculty(self.A, self.A_ds, MON, 3, original_faculty=self.ravi, ignore_adjustment_id=adj.pk)
        self.assertIn("sneha", names(ok))
