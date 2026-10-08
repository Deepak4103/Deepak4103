import datetime
from decimal import Decimal

from academics.models import Holiday, set_setting
from attendance import services as att
from attendance.models import AttendanceSession
from leaves import services as svc
from leaves.models import Adjustment, LeaveRequest, Notification

from .base import MON, SAT, SUN, TUE, WED, LeaveTestCase


class CreateRequestTests(LeaveTestCase):
    def create(self, user=None, faculty=None, **kw):
        args = dict(faculty=faculty or self.ravi, leave_type=self.casual, from_date=MON, to_date=MON, scope="full",
                    created_by=user or self.ravi)
        args.update(kw)
        return svc.create_leave_request(**args)

    def slots(self, req):
        return sorted((a.date, a.period_no, a.school_class.name) for a in svc.leave_adjustments(req))

    def test_one_row_per_period_of_that_faculty_only(self):
        req = self.create()
        self.assertEqual(self.slots(req), [(MON, 1, "A"), (MON, 3, "A")])
        self.assertEqual(req.status, LeaveRequest.DRAFT)

    def test_each_row_records_original_faculty_and_subject(self):
        a = svc.leave_adjustments(self.create()).first()
        self.assertEqual((a.original_faculty, a.original_subject, a.substitute, a.subject_taught),
                         (self.ravi, self.A_ds, None, None))

    def test_multi_day_range_and_sunday_skipped(self):
        req = self.create(user=self.admin, from_date=SAT, to_date=TUE)        # Sat (no periods), Sun, Mon, Tue
        self.assertEqual([d.date for d in req.days.all()], [SAT, MON, TUE])
        self.assertEqual(self.slots(req), [(MON, 1, "A"), (MON, 3, "A"), (TUE, 1, "A")])

    def test_holiday_skipped(self):
        Holiday.objects.create(from_date=MON, to_date=MON, reason="Festival")
        req = self.create(from_date=MON, to_date=TUE)
        self.assertEqual([d.date for d in req.days.all()], [TUE])
        self.assertEqual(self.slots(req), [(TUE, 1, "A")])

    def test_class_specific_holiday_skips_only_that_class(self):
        Holiday.objects.create(from_date=MON, to_date=MON, reason="Class trip", school_class=self.A)
        self.assertEqual(self.slots(self.create()), [])

    def test_leave_only_on_holidays_is_rejected(self):
        with self.assertRaises(svc.LeaveError):
            self.create(from_date=SUN, to_date=SUN)

    def test_half_day_uses_admin_defined_forenoon(self):
        self.assertEqual(self.slots(self.create(scope="forenoon")), [(MON, 1, "A"), (MON, 3, "A")])   # P1-4 by default

    def test_changing_the_forenoon_split(self):
        set_setting("forenoon_last_period", 2)
        self.assertEqual(self.slots(self.create(scope="forenoon")), [(MON, 1, "A")])
        self.assertEqual(self.slots(self.create(scope="afternoon")), [(MON, 3, "A")])

    def test_specific_periods(self):
        self.assertEqual(self.slots(self.create(scope="periods", periods="3")), [(MON, 3, "A")])

    def test_periods_required_for_specific_scope(self):
        with self.assertRaises(svc.LeaveError):
            self.create(scope="periods", periods="")

    def test_period_already_taken_is_not_listed(self):
        self.set_today(MON)
        att.save_attendance(school_class=self.A, date=MON, period_no=1, entry=self.ttA.entries.get(day=0, period_no=1),
                            user=self.admin, absent_ids=set(), topic="x")
        self.assertEqual(self.slots(self.create(user=self.admin)), [(MON, 3, "A")])

    def test_faculty_cannot_apply_for_past_dates_but_admin_can(self):
        self.set_today(WED)
        with self.assertRaises(svc.LeaveError):
            self.create(user=self.ravi)
        req = self.create(user=self.admin)
        self.assertEqual(req.status, LeaveRequest.APPROVED)       # admin entry is approved straight away
        self.assertTrue(req.entered_by_admin)
        self.assertEqual(req.decided_by, self.admin)

    def test_overlapping_leave_rejected(self):
        self.create()
        with self.assertRaises(svc.LeaveError):
            self.create(scope="periods", periods="3")
        # but a different, non-overlapping period set is fine for a half day split
        self.create(from_date=TUE, to_date=TUE)

    def test_cancelled_leave_does_not_block_a_new_one(self):
        req = self.create()
        svc.cancel_request(req, user=self.ravi)
        self.create()

    def test_end_before_start(self):
        with self.assertRaises(svc.LeaveError):
            self.create(from_date=TUE, to_date=MON)


class AdjustmentRuleTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                            scope="full", created_by=self.ravi)
        self.p1, self.p3 = svc.leave_adjustments(self.req).order_by("period_no")

    def test_same_subject_sets_subject_taught_to_original(self):
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=True)
        self.assertEqual(self.p1.subject_taught, self.A_ds)
        self.assertTrue(self.p1.same_subject)

    def test_different_subject_must_come_from_the_same_class(self):
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=False, subject=self.B_ph)
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=False, subject=None)
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=False, subject=self.A_db)
        self.assertEqual(self.p1.subject_taught, self.A_db)
        self.assertFalse(self.p1.same_subject)

    def test_different_subject_cannot_equal_the_original(self):
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=False, subject=self.A_ds)

    def test_ineligible_substitute_rejected(self):
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.ravi, substitute=self.anil, same_subject=True)   # busy + unrelated

    def test_cannot_name_yourself(self):
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.ravi, substitute=self.ravi, same_subject=True)

    def test_draft_adjustment_waits_for_submit(self):
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=True)
        self.assertEqual(self.p1.status, Adjustment.UNASSIGNED)
        self.assertEqual(Notification.objects.filter(user=self.sneha).count(), 0)    # nobody asked yet

    def test_cannot_submit_until_every_period_has_substitute_and_subject(self):
        with self.assertRaises(svc.LeaveError) as ctx:
            svc.submit_request(self.req, user=self.ravi)
        self.assertIn("Every period", str(ctx.exception))
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=True)
        with self.assertRaises(svc.LeaveError):
            svc.submit_request(self.req, user=self.ravi)          # P3 still empty
        svc.set_adjustment(self.p3, user=self.ravi, substitute=self.dev, same_subject=False, subject=self.A_db)
        svc.submit_request(self.req, user=self.ravi)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, LeaveRequest.AWAITING_CONSENT)

    def test_a_request_with_no_periods_can_be_submitted(self):
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=WED, to_date=WED,
                                       scope="full", created_by=self.ravi)
        svc.submit_request(req, user=self.ravi)
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequest.AWAITING_ADMIN)

    def test_only_the_applicant_can_submit(self):
        with self.assertRaises(svc.LeaveError):
            svc.submit_request(self.req, user=self.sneha)

    def test_two_requests_cannot_hold_the_same_substitute_in_one_period(self):
        # Anil is on leave P3 (class B) and picks Sneha for it, while Ravi also wants Sneha for P3 (class A).
        other = svc.create_leave_request(faculty=self.anil, leave_type=self.casual, from_date=MON, to_date=MON,
                                         scope="periods", periods="3", created_by=self.anil)
        a = svc.leave_adjustments(other).get()
        svc.set_adjustment(a, user=self.admin, substitute=self.dev, same_subject=False, subject=self.B_ds)   # dev takes P3
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p3, user=self.ravi, substitute=self.dev, same_subject=True)
        svc.set_adjustment(self.p3, user=self.ravi, substitute=self.sneha, same_subject=True)


class ConsentAndApprovalTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                            scope="full", created_by=self.ravi)
        self.p1, self.p3 = svc.leave_adjustments(self.req).order_by("period_no")
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.sneha, same_subject=True)
        svc.set_adjustment(self.p3, user=self.ravi, substitute=self.dev, same_subject=True)
        svc.submit_request(self.req, user=self.ravi)
        self.p1.refresh_from_db()
        self.p3.refresh_from_db()

    def fresh(self):
        self.req.refresh_from_db()
        return self.req.status

    def test_submit_asks_each_substitute(self):
        self.assertEqual((self.p1.status, self.p3.status), (Adjustment.PENDING, Adjustment.PENDING))
        self.assertTrue(Notification.objects.filter(user=self.sneha, text__contains="accept or decline").exists())
        self.assertTrue(Notification.objects.filter(user=self.dev).exists())

    def test_goes_to_admin_only_after_all_accept(self):
        svc.respond(self.p1, user=self.sneha, accept=True)
        self.assertEqual(self.fresh(), LeaveRequest.AWAITING_CONSENT)
        svc.respond(self.p3, user=self.dev, accept=True)
        self.assertEqual(self.fresh(), LeaveRequest.AWAITING_ADMIN)
        self.assertTrue(Notification.objects.filter(user=self.admin, text__contains="ready for approval").exists())

    def test_only_the_chosen_substitute_can_answer(self):
        with self.assertRaises(svc.LeaveError):
            svc.respond(self.p1, user=self.dev, accept=True)
        with self.assertRaises(svc.LeaveError):
            svc.respond(self.p1, user=self.ravi, accept=True)

    def test_answer_cannot_be_given_twice(self):
        svc.respond(self.p1, user=self.sneha, accept=True)
        with self.assertRaises(svc.LeaveError):
            svc.respond(self.p1, user=self.sneha, accept=False)

    def test_decline_asks_applicant_to_choose_someone_else(self):
        svc.respond(self.p1, user=self.sneha, accept=False)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.status, Adjustment.DECLINED)
        self.assertEqual(self.fresh(), LeaveRequest.AWAITING_CONSENT)
        self.assertTrue(Notification.objects.filter(user=self.ravi, text__contains="declined").exists())
        svc.respond(self.p3, user=self.dev, accept=True)
        self.assertEqual(self.fresh(), LeaveRequest.AWAITING_CONSENT)      # still blocked by the declined one
        # applicant picks Dev for P1? Dev holds P3 only, so he is free in P1
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.dev, same_subject=True)
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.substitute, self.p1.status), (self.dev, Adjustment.PENDING))
        svc.respond(self.p1, user=self.dev, accept=True)
        self.assertEqual(self.fresh(), LeaveRequest.AWAITING_ADMIN)

    def test_changing_substitute_after_submit_resets_consent(self):
        svc.respond(self.p1, user=self.sneha, accept=True)
        svc.set_adjustment(self.p1, user=self.ravi, substitute=self.dev, same_subject=False, subject=self.A_db)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.status, Adjustment.PENDING)
        self.assertTrue(Notification.objects.filter(user=self.sneha, text__contains="no longer").exists())

    def test_accept_fails_if_substitute_became_busy(self):
        self.ttB.entries.filter(day=0, period_no=1).update(faculty=self.sneha)     # new commitment in P1 after she was asked
        with self.assertRaises(svc.LeaveError):
            svc.respond(self.p1, user=self.sneha, accept=True)

    def test_admin_approves(self):
        svc.respond(self.p1, user=self.sneha, accept=True)
        svc.respond(self.p3, user=self.dev, accept=True)
        svc.decide(self.req, admin=self.admin, approve=True)
        self.assertEqual(self.fresh(), LeaveRequest.APPROVED)
        self.assertEqual(self.req.decided_by, self.admin)

    def test_admin_cannot_approve_before_substitutes_accept(self):
        with self.assertRaises(svc.LeaveError):
            svc.decide(self.req, admin=self.admin, approve=True)

    def test_reject_cancels_adjustments_and_frees_substitutes(self):
        svc.respond(self.p1, user=self.sneha, accept=True)
        svc.respond(self.p3, user=self.dev, accept=True)
        svc.decide(self.req, admin=self.admin, approve=False, note="Exams that week")
        self.assertEqual(self.fresh(), LeaveRequest.REJECTED)
        self.assertEqual(self.req.adjustments.exclude(status=Adjustment.CANCELLED).count(), 0)
        self.assertTrue(Notification.objects.filter(user=self.sneha, text__contains="rejected").exists())
        self.assertTrue(Notification.objects.filter(user=self.ravi, text__contains="Exams").exists())

    def test_faculty_cannot_edit_after_approval(self):
        svc.respond(self.p1, user=self.sneha, accept=True)
        svc.respond(self.p3, user=self.dev, accept=True)
        svc.decide(self.req, admin=self.admin, approve=True)
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.ravi, substitute=self.dev, same_subject=True)
        with self.assertRaises(svc.LeaveError):
            svc.cancel_request(self.req, user=self.ravi)
        svc.cancel_request(self.req, user=self.admin)            # admin can
        self.assertEqual(self.fresh(), LeaveRequest.CANCELLED)

    def test_applicant_can_cancel_before_approval(self):
        svc.cancel_request(self.req, user=self.ravi)
        self.assertEqual(self.fresh(), LeaveRequest.CANCELLED)
        self.assertEqual(self.req.adjustments.exclude(status=Adjustment.CANCELLED).count(), 0)
        self.assertTrue(Notification.objects.filter(user=self.sneha, text__contains="cancelled").exists())


class AdminPowerTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.set_today(WED)                                             # the leave below is in the past
        self.req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                            scope="full", created_by=self.admin)
        self.p1, self.p3 = svc.leave_adjustments(self.req).order_by("period_no")

    def test_admin_can_enter_past_leave_for_anyone(self):
        self.assertEqual(self.req.status, LeaveRequest.APPROVED)

    def test_admin_adjustment_needs_no_consent_and_substitute_is_notified(self):
        svc.set_adjustment(self.p1, user=self.admin, substitute=self.sneha, same_subject=False, subject=self.A_db)
        self.assertEqual((self.p1.status, self.p1.consent_required, self.p1.made_by_role),
                         (Adjustment.ACCEPTED, False, "admin"))
        n = Notification.objects.get(user=self.sneha)
        self.assertIn("assigned you", n.text)

    def test_admin_can_change_and_cancel(self):
        svc.set_adjustment(self.p1, user=self.admin, substitute=self.sneha, same_subject=True)
        svc.set_adjustment(self.p1, user=self.admin, substitute=self.dev, same_subject=True)
        self.assertEqual(self.p1.substitute, self.dev)
        svc.clear_adjustment(self.p1, user=self.admin)
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.substitute, self.p1.subject_taught, self.p1.status), (None, None, Adjustment.UNASSIGNED))
        with self.assertRaises(svc.LeaveError):
            svc.clear_adjustment(self.p1, user=self.ravi)

    def test_admin_cannot_change_after_attendance_was_taken(self):
        svc.set_adjustment(self.p1, user=self.admin, substitute=self.sneha, same_subject=True)
        entry = self.ttA.entries.get(day=0, period_no=1)
        adj = att.find_adjustment(self.A, MON, 1)
        att.save_attendance(school_class=self.A, date=MON, period_no=1, entry=entry, user=self.sneha,
                            absent_ids=set(), topic="Trees", adjustment=adj)
        with self.assertRaises(svc.LeaveError):
            svc.set_adjustment(self.p1, user=self.admin, substitute=self.dev, same_subject=True)

    def test_unadjusted_list_nearest_first_and_only_open_items(self):
        self.set_today(MON)
        svc.set_adjustment(self.p3, user=self.admin, substitute=self.dev, same_subject=True)      # fixed: not listed
        later = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=TUE, to_date=TUE,
                                         scope="full", created_by=self.admin)                       # Tuesday P1 open
        items = svc.unadjusted_periods(on=MON)
        self.assertEqual([(a.date, a.period_no) for a in items], [(MON, 1), (TUE, 1)])
        # a declined/pending one is listed too; a draft or rejected request is not
        far = svc.create_leave_request(faculty=self.sneha, leave_type=self.casual, from_date=datetime.date(2026, 10, 12),
                                       to_date=datetime.date(2026, 10, 12), scope="full", created_by=self.admin)
        self.assertEqual(len(svc.unadjusted_periods(on=MON)), 4)
        self.assertEqual(svc.unadjusted_periods(on=MON)[-1].date, datetime.date(2026, 10, 12))
        svc.cancel_request(far, user=self.admin)
        self.assertEqual(len(svc.unadjusted_periods(on=MON)), 2)

    def test_awaiting_substitute_counts_as_unadjusted(self):
        self.set_today(SUN)
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=TUE, to_date=TUE,
                                       scope="full", created_by=self.ravi)
        a = svc.leave_adjustments(req).get()
        self.assertEqual([x for x in svc.unadjusted_periods(on=SUN) if x.pk == a.pk], [])      # draft: not listed
        svc.set_adjustment(a, user=self.ravi, substitute=self.sneha, same_subject=True)
        svc.submit_request(req, user=self.ravi)
        listed = [x for x in svc.unadjusted_periods(on=SUN) if x.pk == a.pk]
        self.assertEqual(len(listed), 1)                                  # pending acceptance
        svc.respond(a, user=self.sneha, accept=True)
        self.assertEqual([x for x in svc.unadjusted_periods(on=SUN) if x.pk == a.pk], [])


class BalanceTests(LeaveTestCase):
    def make(self, scope="full", faculty=None, day=MON, admin=True, **kw):
        return svc.create_leave_request(faculty=faculty or self.ravi, leave_type=self.casual, from_date=day, to_date=kw.pop("to", day),
                                        scope=scope, created_by=self.admin if admin else self.ravi, **kw)

    def balance(self):
        return next(r for r in svc.leave_balance(self.ravi, 2026) if r["type"] == self.casual)

    def test_starts_full(self):
        b = self.balance()
        self.assertEqual((b["allowed"], b["used"], b["remaining"], b["exhausted"]), (Decimal("12.0"), 0, Decimal("12.0"), False))

    def test_deducted_on_approval_only(self):
        req = self.make(admin=False)
        self.assertEqual(self.balance()["used"], 0)
        self.assertEqual(self.balance()["waiting"], Decimal("1.0"))
        for a in svc.leave_adjustments(req):
            svc.set_adjustment(a, user=self.admin, substitute=self.sneha if a.period_no == 1 else self.dev, same_subject=True)
        svc.submit_request(req, user=self.ravi)       # the admin already fixed everyone, so it goes straight to approval
        req.refresh_from_db()
        self.assertEqual(req.status, LeaveRequest.AWAITING_ADMIN)
        svc.decide(req, admin=self.admin, approve=True)
        self.assertEqual(self.balance()["used"], Decimal("1.0"))
        self.assertEqual(self.balance()["waiting"], 0)

    def test_half_day_and_periods_count_half(self):
        self.make(scope="forenoon")
        self.make(scope="periods", periods="1", day=TUE)
        self.assertEqual(self.balance()["used"], Decimal("1.0"))

    def test_holidays_inside_a_range_are_not_counted(self):
        self.make(day=SAT, to=TUE)                     # Sat, (Sun skipped), Mon, Tue
        self.assertEqual(self.balance()["used"], Decimal("3.0"))

    def test_rejected_and_cancelled_do_not_deduct(self):
        req = self.make()
        svc.cancel_request(req, user=self.admin)
        self.assertEqual(self.balance()["used"], 0)

    def test_warns_when_balance_is_exhausted_or_exceeded(self):
        self.casual.days_per_year = Decimal("2.0")
        self.casual.save()
        req = self.make(day=MON, to=TUE)                # 2 days: exactly the balance, admin-entered -> approved
        self.assertTrue(self.balance()["exhausted"])
        self.assertIn("exhausted", svc.balance_warning(req))
        # a new request when nothing is left
        self.set_today(SUN)
        pending = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=datetime.date(2026, 10, 12),
                                           to_date=datetime.date(2026, 10, 12), scope="full", created_by=self.ravi)
        self.assertIn("exhausted", svc.balance_warning(pending))

    def test_warns_when_request_exceeds_remaining(self):
        self.casual.days_per_year = Decimal("1.0")
        self.casual.save()
        req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=TUE,
                                       scope="full", created_by=self.ravi)
        self.assertIn("exceeds", svc.balance_warning(req))

    def test_inactive_type_not_in_balance_and_not_offered(self):
        self.casual.active = False
        self.casual.save()
        self.assertEqual(svc.leave_balance(self.ravi, 2026), [])

    def test_balance_is_per_calendar_year(self):
        self.make()
        self.assertEqual(next(r for r in svc.leave_balance(self.ravi, 2027))["used"], 0)


class ReturnTests(LeaveTestCase):
    def setUp(self):
        super().setUp()
        self.req = svc.create_leave_request(faculty=self.ravi, leave_type=self.casual, from_date=MON, to_date=MON,
                                            scope="periods", periods="1", created_by=self.ravi)
        a = svc.leave_adjustments(self.req).get()
        svc.set_adjustment(a, user=self.ravi, substitute=self.sneha, same_subject=True)
        svc.submit_request(self.req, user=self.ravi)
        svc.respond(a, user=self.sneha, accept=True)
        svc.decide(self.req, admin=self.admin, approve=True)
        self.req.refresh_from_db()
        # Sneha's Monday P2 class A (DB) -> next Monday, Ravi takes it in exchange
        self.next_mon = datetime.date(2026, 10, 12)

    def test_candidates_are_the_substitutes_periods_the_applicant_can_take(self):
        cands = svc.return_candidates(self.req, self.sneha, self.next_mon)
        self.assertEqual([(c.name, e.period_no) for c, e in cands], [("A", 2), ("A", 4)])   # Ravi free at P2/P4

    def test_offer_needs_the_substitutes_consent_then_is_in_force(self):
        adj = svc.offer_return(self.req, user=self.ravi, school_class=self.A, date=self.next_mon, period_no=2,
                               same_subject=False, subject=self.A_ds)
        self.assertEqual((adj.kind, adj.original_faculty, adj.substitute, adj.status),
                         (Adjustment.RETURN, self.sneha, self.ravi, Adjustment.PENDING))
        self.assertEqual((adj.original_subject, adj.subject_taught), (self.A_db, self.A_ds))
        self.assertIsNone(att.find_adjustment(self.A, self.next_mon, 2))          # not yet
        svc.respond(adj, user=self.sneha, accept=True)                            # Sneha answers (not Ravi)
        adj.refresh_from_db()
        self.assertEqual(att.find_adjustment(self.A, self.next_mon, 2), adj)
        self.assertEqual(att.responsible_faculty_id(self.ttA.entries.get(day=0, period_no=2), adj, self.next_mon),
                         self.ravi.pk)

    def test_applicant_cannot_accept_their_own_offer(self):
        adj = svc.offer_return(self.req, user=self.ravi, school_class=self.A, date=self.next_mon, period_no=2, same_subject=True)
        with self.assertRaises(svc.LeaveError):
            svc.respond(adj, user=self.ravi, accept=True)

    def test_can_only_take_a_period_of_someone_who_covered(self):
        with self.assertRaises(svc.LeaveError):
            svc.offer_return(self.req, user=self.ravi, school_class=self.B, date=self.next_mon, period_no=2, same_subject=True)

    def test_cannot_offer_a_period_already_adjusted(self):
        svc.offer_return(self.req, user=self.ravi, school_class=self.A, date=self.next_mon, period_no=2, same_subject=True)
        with self.assertRaises(svc.LeaveError):
            svc.offer_return(self.req, user=self.ravi, school_class=self.A, date=self.next_mon, period_no=2, same_subject=True)

    def test_admin_return_needs_no_consent(self):
        adj = svc.offer_return(self.req, user=self.admin, school_class=self.A, date=self.next_mon, period_no=4, same_subject=True)
        self.assertEqual(adj.status, Adjustment.ACCEPTED)
        self.assertEqual(adj.made_by_role, "admin")

    def test_return_not_allowed_for_past_dates_by_faculty(self):
        self.set_today(self.next_mon)
        with self.assertRaises(svc.LeaveError):
            svc.offer_return(self.req, user=self.ravi, school_class=self.A, date=TUE, period_no=2, same_subject=True)
