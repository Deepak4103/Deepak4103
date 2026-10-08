"""Leave + adjustments flowing through to the substitute's day, attendance records and the screens."""
from django.urls import reverse

from attendance import services as att
from attendance.models import AttendanceSession
from leaves import services as svc
from leaves.models import Adjustment, LeaveRequest

from .base import MON, TUE, WED, LeaveTestCase


class AdjustedPeriodFlowTests(LeaveTestCase):
    """Ravi (DS, class A) is on approved leave on Monday. P1: Sneha, different subject (Databases).
    P3: Dev, same subject."""

    def setUp(self):
        super().setUp()
        self.req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                            scope="full", created_by=self.ravi)
        self.p1, self.p3 = svc.leave_adjustments(self.req).order_by("period_no")
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=False, subject=self.A_db)
        svc.set_adjustment(self.p3, user=self.ravi, substitute=self.dev, same_subject=True)
        svc.submit_request(self.req, user=self.ravi)
        svc.respond(self.p1, user=self.sneha, accept=True)
        svc.respond(self.p3, user=self.dev, accept=True)
        self.set_today(MON)

    def approve(self):
        svc.decide(self.req, admin=self.admin, approve=True)

    def day(self, user):
        todays, pending = att.faculty_day_and_pending(user, MON)
        return todays, pending

    def mark(self, user, period=1, absent=(), topic="Joins", cls=None):
        self.client.force_login(user)
        return self.client.post(reverse("mark_attendance", args=[(cls or self.A).pk, MON, period]),
                                {"topic": topic, "absent": [s.pk for s in absent]})

    def test_not_in_force_until_the_admin_approves(self):
        todays, _ = self.day(self.sneha)
        self.assertEqual([(s.period_no, s.is_adjusted) for s in todays], [(2, False), (4, False)])
        todays, pending = self.day(self.ravi)                         # Ravi still owns his periods
        self.assertEqual([s.period_no for s in todays], [1, 3])

    def test_substitute_sees_it_labelled_with_the_subject_to_teach(self):
        self.approve()
        todays, _ = self.day(self.sneha)
        adjusted = [s for s in todays if s.is_adjusted]
        self.assertEqual(len(adjusted), 1)
        s = adjusted[0]
        self.assertEqual((s.period_no, s.adjusted_for, s.subject, s.entry.subject),
                         (1, self.ravi, self.A_db, self.A_ds))
        self.client.force_login(self.sneha)
        r = self.client.get(reverse("faculty_home"))
        self.assertContains(r, "Adjustment for Ravi")

    def test_no_longer_pending_for_the_faculty_on_leave(self):
        self.approve()
        todays, pending = self.day(self.ravi)
        self.assertEqual(todays, [])
        self.assertEqual([p for p in pending if p.date == MON], [])
        self.client.force_login(self.ravi)
        r = self.client.get(reverse("faculty_home"))
        self.assertEqual(r.context["pending_today"], [])         # (earlier weeks may still be pending)
        self.assertEqual(r.context["slots"], [])

    def test_substitute_period_is_pending_for_the_substitute(self):
        self.approve()
        _, pending = self.day(self.dev)
        self.assertIn((MON, 3, "A"), [(s.date, s.period_no, s.school_class.name) for s in pending])

    def test_attendance_counts_under_subject_taught_and_credits_the_substitute(self):
        self.approve()
        self.assertEqual(self.mark(self.sneha, period=1, absent=[]).status_code, 302)
        s = AttendanceSession.objects.get(period_no=1)
        self.assertEqual(s.subject, self.A_db)                  # actually taught
        self.assertEqual(s.scheduled_subject, self.A_ds)        # timetable
        self.assertEqual(s.taken_by, self.sneha)                # credited to the substitute
        self.assertEqual(s.scheduled_faculty, self.ravi)        # original faculty kept
        self.assertEqual(s.adjustment, self.p1)
        self.assertEqual(s.adjustment.made_by_role, "faculty")
        # the substitute's own log, and not Ravi's
        self.client.force_login(self.sneha)
        self.assertContains(self.client.get(reverse("records")), "Joins")
        self.client.force_login(self.ravi)
        self.assertEqual(self.client.get(reverse("session_detail", args=[s.pk])).status_code, 403)

    def test_same_subject_adjustment_counts_under_the_original_subject(self):
        self.approve()
        self.mark(self.dev, period=3, topic="Heaps")
        s = AttendanceSession.objects.get(period_no=3)
        self.assertEqual((s.subject, s.taken_by), (self.A_ds, self.dev))
        self.assertTrue(s.adjustment.same_subject)

    def test_period_is_completed_for_the_substitute_after_marking(self):
        self.approve()
        self.mark(self.sneha, period=1)
        todays, pending = self.day(self.sneha)
        self.assertTrue(next(s for s in todays if s.period_no == 1).completed)
        self.assertEqual([s for s in pending if s.period_no == 1], [])

    def test_original_faculty_cannot_mark_a_period_given_away(self):
        self.approve()
        self.assertEqual(self.mark(self.ravi, period=1).status_code, 403)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_someone_else_cannot_mark_it_either(self):
        self.approve()
        self.assertEqual(self.mark(self.dev, period=1).status_code, 403)

    def test_substitute_cannot_mark_a_period_that_is_not_theirs(self):
        self.approve()
        self.assertEqual(self.mark(self.sneha, period=3).status_code, 403)       # P3 went to Dev

    def test_same_period_cannot_be_entered_twice_even_via_adjustment(self):
        self.approve()
        self.mark(self.sneha, period=1)
        self.mark(self.sneha, period=1, topic="Again")                            # edit, not a duplicate
        self.assertEqual(AttendanceSession.objects.filter(period_no=1).count(), 1)
        self.assertEqual(AttendanceSession.objects.get(period_no=1).topic, "Again")

    def test_admin_entering_attendance_for_an_adjusted_period_is_credited_to_the_substitute(self):
        self.approve()
        self.mark(self.admin, period=1)
        s = AttendanceSession.objects.get(period_no=1)
        self.assertEqual((s.taken_by, s.subject), (self.sneha, self.A_db))

    def test_monitoring_shows_the_adjustment_with_both_subjects(self):
        self.approve()
        self.client.force_login(self.admin)
        r = self.client.get(reverse("monitor"), {"date": MON.isoformat()})
        self.assertContains(r, "Adjusted for Ravi")
        self.assertContains(r, "timetable: Data Structures")

    def test_cancelling_the_leave_returns_the_period_to_the_timetable_faculty(self):
        self.approve()
        svc.cancel_request(self.req, user=self.admin)
        todays, _ = self.day(self.ravi)
        self.assertEqual([s.period_no for s in todays], [1, 3])
        todays, _ = self.day(self.sneha)
        self.assertFalse(any(s.is_adjusted for s in todays))

    def test_admin_can_cancel_one_adjustment_leaving_the_period_unadjusted(self):
        self.approve()
        svc.clear_adjustment(self.p1, user=self.admin)
        todays, pending = self.day(self.ravi)
        self.assertEqual([s.period_no for s in todays], [])      # still on leave: not his, and not pending
        index = att.ScheduleIndex(MON, MON)
        slot = next(s for s in index.slots(MON, class_id=self.A.pk) if s.period_no == 1)
        self.assertTrue(slot.unadjusted)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("monitor"), {"date": MON.isoformat()}), "On leave - no substitute")
        self.assertIn(self.p1.pk, [a.pk for a in svc.unadjusted_periods(on=MON)])

    def test_unadjusted_leave_period_is_not_pending_for_faculty_on_leave(self):
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=TUE, to_date=TUE,
                                       scope="full", created_by=self.admin)       # approved, nobody fixed
        _, pending = att.faculty_day_and_pending(self.ravi, TUE)
        self.assertEqual([p for p in pending if p.date == TUE], [])


class LeaveScreenTests(LeaveTestCase):
    def post(self, user, name, args=(), data=None):
        self.client.force_login(user)
        return self.client.post(reverse(name, args=args), data or {})

    def test_faculty_applies_then_fills_in_and_submits(self):
        self.client.force_login(self.ravi)
        r = self.client.post(reverse("leave_apply"), {"leave_type": self.casual.pk, "from_date": MON.isoformat(),
                                                      "to_date": MON.isoformat(), "scope": "full", "reason": "Wedding"})
        req = LeaveRequest.objects.get()
        self.assertRedirects(r, reverse("leave_detail", args=[req.pk]))
        page = self.client.get(reverse("leave_detail", args=[req.pk]))
        self.assertContains(page, "Substitute")
        self.assertContains(page, "Sneha")
        self.assertNotContains(page, "Anil")                  # not eligible
        p1, p3 = svc.leave_adjustments(req).order_by("period_no")
        # submit with nothing filled in: refused
        r = self.client.post(reverse("leave_adjust", args=[req.pk]), {"action": "submit"}, follow=True)
        self.assertContains(r, "Every period needs a substitute")
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequest.DRAFT)
        data = {"action": "submit", f"sub_{p1.pk}": self.sneha.pk, f"mode_{p1.pk}": "diff", f"subj_{p1.pk}": self.A_db.pk,
                f"sub_{p3.pk}": self.dev.pk, f"mode_{p3.pk}": "same"}
        r = self.client.post(reverse("leave_adjust", args=[req.pk]), data, follow=True)
        self.assertContains(r, "Request submitted")
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequest.AWAITING_CONSENT)
        p1.refresh_from_db()
        self.assertEqual((p1.substitute, p1.subject_taught, p1.status), (self.sneha, self.A_db, Adjustment.PENDING))

    def test_substitute_accepts_from_home_screen(self):
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                       scope="periods", periods="1", created_by=self.ravi)
        a = svc.leave_adjustments(req).get()
        svc.set_adjustment(a, user=self.ravi, substitute=self.sneha, same_subject=True)
        svc.submit_request(req, user=self.ravi)
        self.client.force_login(self.sneha)
        home = self.client.get(reverse("faculty_home"))
        self.assertContains(home, "waiting for your answer")
        self.assertContains(home, "Ravi")
        # someone else cannot answer for her
        self.assertContains(self.post(self.dev, "adjustment_respond", [a.pk], {"answer": "accept"}), "", status_code=302)
        a.refresh_from_db()
        self.assertEqual(a.status, Adjustment.PENDING)
        self.post(self.sneha, "adjustment_respond", [a.pk], {"answer": "accept"})
        a.refresh_from_db()
        self.assertEqual(a.status, Adjustment.ACCEPTED)

    def test_decline_shows_the_applicant_a_prompt_to_choose_again(self):
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                       scope="periods", periods="1", created_by=self.ravi)
        a = svc.leave_adjustments(req).get()
        svc.set_adjustment(a, user=self.ravi, substitute=self.sneha, same_subject=True)
        svc.submit_request(req, user=self.ravi)
        self.post(self.sneha, "adjustment_respond", [a.pk], {"answer": "decline"})
        self.client.force_login(self.ravi)
        home = self.client.get(reverse("faculty_home"))
        self.assertContains(home, "declined")
        self.assertContains(home, "choose another substitute")

    def test_other_faculty_cannot_open_someone_elses_leave(self):
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                       scope="full", created_by=self.ravi)
        self.client.force_login(self.sneha)
        for name in ("leave_detail", "leave_adjust", "leave_cancel"):
            r = self.client.post(reverse(name, args=[req.pk])) if name != "leave_detail" else self.client.get(reverse(name, args=[req.pk]))
            self.assertEqual(r.status_code, 403, name)

    def test_only_admin_can_decide_and_manage(self):
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                       scope="full", created_by=self.ravi)
        self.client.force_login(self.ravi)
        for name, args in (("leave_decide", [req.pk]), ("unadjusted", []), ("leave_list", []), ("leave_balances", []),
                           ("leave_type_list", []), ("period_settings", [])):
            r = self.client.post(reverse(name, args=args)) if name == "leave_decide" else self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 403, name)

    def test_admin_enters_leave_for_a_past_date_on_behalf(self):
        self.set_today(WED)
        self.client.force_login(self.admin)
        r = self.client.post(reverse("leave_new_admin"), {
            "faculty": self.ravi.pk, "leave_type": self.casual.pk, "from_date": MON.isoformat(),
            "to_date": MON.isoformat(), "scope": "full"})
        req = LeaveRequest.objects.get()
        self.assertRedirects(r, reverse("leave_detail", args=[req.pk]))
        self.assertEqual((req.faculty, req.status, req.created_by), (self.ravi, LeaveRequest.APPROVED, self.admin))
        a = svc.leave_adjustments(req).order_by("period_no").first()
        data = {f"sub_{a.pk}": self.sneha.pk, f"mode_{a.pk}": "same"}
        self.client.post(reverse("leave_adjust", args=[req.pk]), data)
        a.refresh_from_db()
        self.assertEqual((a.status, a.made_by_role), (Adjustment.ACCEPTED, "admin"))

    def test_faculty_cannot_use_the_admin_form_to_apply_for_someone_else(self):
        self.client.force_login(self.ravi)
        self.client.post(reverse("leave_new_admin"), {"faculty": self.sneha.pk, "leave_type": self.casual.pk,
                         "from_date": MON.isoformat(), "to_date": MON.isoformat(), "scope": "full"})
        self.assertEqual(LeaveRequest.objects.get().faculty, self.ravi)

    def test_faculty_past_date_form_error(self):
        self.set_today(WED)
        self.client.force_login(self.ravi)
        r = self.client.post(reverse("leave_apply"), {"leave_type": self.casual.pk, "from_date": MON.isoformat(),
                                                      "to_date": MON.isoformat(), "scope": "full"})
        self.assertContains(r, "past date")
        self.assertEqual(LeaveRequest.objects.count(), 0)

    def test_admin_dashboard_lists_unadjusted_and_waiting(self):
        svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON, scope="full",
                                 created_by=self.admin)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("admin_home"))
        self.assertContains(r, "Unadjusted periods (2)")
        self.assertContains(r, "no substitute")

    def test_leave_type_management(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("leave_type_add"), {"name": "Maternity Leave", "days_per_year": "90.0", "active": "on"})
        self.assertTrue(self.casual.__class__.objects.filter(name="Maternity Leave").exists())
        used = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                        scope="full", created_by=self.admin)
        r = self.client.post(reverse("leave_type_delete", args=[self.casual.pk]), follow=True)
        self.assertContains(r, "Untick")
        self.assertTrue(self.casual.__class__.objects.filter(pk=self.casual.pk).exists())

    def test_forenoon_setting_page(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("period_settings"), {"forenoon_last_period": 3})
        from academics.models import forenoon_last_period
        self.assertEqual(forenoon_last_period(), 3)
        r = self.client.post(reverse("period_settings"), {"forenoon_last_period": 7})
        self.assertEqual(forenoon_last_period(), 3)

    def test_notifications_can_be_dismissed(self):
        svc.notify(self.ravi, "Hello there")
        self.client.force_login(self.ravi)
        self.assertContains(self.client.get(reverse("faculty_home")), "Hello there")
        self.client.post(reverse("notifications_clear"))
        self.assertNotContains(self.client.get(reverse("faculty_home")), "Hello there")
