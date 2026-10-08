import datetime

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from academics.models import Holiday
from attendance import services as svc
from attendance.models import AttendanceRecord, AttendanceSession
from timetable.models import Timetable, TimetableEntry

from .base import MON, SUN, TUE, WED, AttendanceTestCase, at


def mark(testcase, user, date=MON, period=1, absent=(), topic="Stacks", cls=None):
    testcase.client.force_login(user)
    cls = cls or testcase.c
    return testcase.client.post(reverse("mark_attendance", args=[cls.pk, date, period]),
                                {"topic": topic, "remarks": "", "absent": [s.pk for s in absent]})


class SavingTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.set_today(MON)

    def test_everyone_present_unless_marked_absent(self):
        r = mark(self, self.ravi, absent=[self.students[1]])
        self.assertEqual(r.status_code, 302)
        s = AttendanceSession.objects.get()
        self.assertEqual(s.subject, self.ds)
        self.assertEqual(s.taken_by, self.ravi)
        self.assertEqual(s.records.count(), 4)
        self.assertEqual(list(s.records.filter(present=False).values_list("student__roll_no", flat=True)), ["R2"])
        self.assertEqual(svc.session_counts(s), (3, 1))

    def test_topic_is_required(self):
        for topic in ("", "   "):
            r = mark(self, self.ravi, topic=topic)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "topic covered")
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_service_rejects_blank_topic(self):
        with self.assertRaises(svc.AttendanceError):
            svc.save_attendance(school_class=self.c, date=MON, period_no=1, entry=self.e1, user=self.ravi,
                                absent_ids=set(), topic=" ")

    def test_same_class_date_period_cannot_be_entered_twice(self):
        mark(self, self.ravi)
        with self.assertRaises(svc.DuplicateAttendance):
            svc.save_attendance(school_class=self.c, date=MON, period_no=1, entry=self.e1, user=self.ravi,
                                absent_ids=set(), topic="Again")
        self.assertEqual(AttendanceSession.objects.count(), 1)
        self.assertEqual(AttendanceRecord.objects.count(), 4)   # no half-written second copy

    def test_second_post_edits_instead_of_duplicating(self):
        mark(self, self.ravi, absent=[self.students[0]])
        mark(self, self.ravi, absent=[self.students[1]], topic="Queues")
        self.assertEqual(AttendanceSession.objects.count(), 1)
        s = AttendanceSession.objects.get()
        self.assertEqual(s.topic, "Queues")
        self.assertEqual(list(s.records.filter(present=False).values_list("student__roll_no", flat=True)), ["R2"])

    def test_different_period_or_date_is_not_a_duplicate(self):
        mark(self, self.ravi)
        mark(self, self.sneha, period=2)
        self.set_today(MON + datetime.timedelta(days=7))
        mark(self, self.ravi, date=MON + datetime.timedelta(days=7))
        self.assertEqual(AttendanceSession.objects.count(), 3)

    def test_faculty_can_only_mark_own_period(self):
        r = mark(self, self.sneha, period=1)       # period 1 belongs to Ravi
        self.assertEqual(r.status_code, 403)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_period_not_in_timetable_is_404(self):
        self.assertEqual(mark(self, self.ravi, period=5).status_code, 404)

    def test_cannot_mark_future_date(self):
        self.set_today(SUN)
        r = mark(self, self.ravi)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_cannot_mark_holiday(self):
        Holiday.objects.create(from_date=MON, to_date=MON, reason="Festival")
        mark(self, self.ravi)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_absent_ids_of_other_classes_are_ignored(self):
        mark(self, self.ravi)
        s = AttendanceSession.objects.get()
        svc.update_attendance(s, user=self.ravi, absent_ids={999999, self.students[0].pk}, topic="x")
        self.assertEqual(s.records.filter(present=False).count(), 1)

    def test_admin_can_fill_a_missing_period_credited_to_scheduled_faculty(self):
        mark(self, self.admin, period=2)
        s = AttendanceSession.objects.get()
        self.assertEqual(s.taken_by, self.sneha)


class LockingTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.set_today(MON)
        mark(self, self.ravi)
        self.s = AttendanceSession.objects.get()

    def test_faculty_can_edit_same_day(self):
        self.assertTrue(svc.can_edit_session(self.ravi, self.s))

    def test_locked_the_next_day(self):
        self.set_entered_on(self.s, MON)
        self.set_today(TUE)
        self.assertFalse(svc.can_edit_session(self.ravi, self.s))
        r = mark(self, self.ravi, date=MON, topic="Sneaky change")
        self.assertRedirects(r, reverse("session_detail", args=[self.s.pk]))
        self.s.refresh_from_db()
        self.assertEqual(self.s.topic, "Stacks")

    def test_admin_can_always_edit(self):
        self.set_entered_on(self.s, MON)
        self.set_today(WED)
        self.assertTrue(svc.can_edit_session(self.admin, self.s))
        mark(self, self.admin, topic="Corrected by admin", absent=[self.students[2]])
        self.s.refresh_from_db()
        self.assertEqual(self.s.topic, "Corrected by admin")
        self.assertEqual(self.s.audits.count(), 1)

    def test_admin_unlock_then_relock_after_faculty_saves(self):
        self.set_entered_on(self.s, MON)
        self.set_today(WED)
        self.assertFalse(svc.can_edit_session(self.ravi, self.s))
        self.client.force_login(self.admin)
        self.client.post(reverse("session_unlock", args=[self.s.pk]), {"unlock": "1"})
        self.s.refresh_from_db()
        self.assertTrue(svc.can_edit_session(self.ravi, self.s))
        mark(self, self.ravi, topic="Fixed typo")
        self.s.refresh_from_db()
        self.assertEqual(self.s.topic, "Fixed typo")
        self.assertFalse(self.s.unlocked)
        self.assertFalse(svc.can_edit_session(self.ravi, self.s))

    def test_late_entry_is_editable_on_the_day_it_was_entered(self):
        self.set_today(TUE)
        mark(self, self.sneha, date=MON, period=2, topic="Entered late")
        late = AttendanceSession.objects.get(period_no=2)
        self.set_entered_on(late, TUE)                  # entered on Tuesday for Monday's class
        self.assertTrue(svc.can_edit_session(self.sneha, late))
        self.set_today(WED)
        self.assertFalse(svc.can_edit_session(self.sneha, late))

    def test_faculty_cannot_edit_someone_elses_record(self):
        with self.assertRaises(PermissionDenied):
            svc.update_attendance(self.s, user=self.sneha, absent_ids=set(), topic="hijack")

    def test_only_admin_can_unlock(self):
        self.client.force_login(self.ravi)
        r = self.client.post(reverse("session_unlock", args=[self.s.pk]), {"unlock": "1"})
        self.assertEqual(r.status_code, 403)

    def test_edit_is_audited(self):
        svc.update_attendance(self.s, user=self.ravi, absent_ids={self.students[0].pk}, topic="Stacks II")
        audit = self.s.audits.get()
        self.assertIn("Stacks II", audit.summary)
        self.assertIn("+R1", audit.summary)


class PendingTests(AttendanceTestCase):
    def pending(self, user, on):
        return svc.faculty_day_and_pending(user, on)

    def test_pending_includes_today_and_earlier_until_completed(self):
        # Mondays: 5 Oct and 12 Oct; 'today' is 12 Oct
        today = MON + datetime.timedelta(days=7)
        self.set_today(today)
        _, pending = self.pending(self.ravi, today)
        self.assertEqual([(s.date, s.period_no) for s in pending], [(MON, 1), (today, 1)])
        mark(self, self.ravi, date=MON)                       # complete the earlier one
        _, pending = self.pending(self.ravi, today)
        self.assertEqual([(s.date, s.period_no) for s in pending], [(today, 1)])

    def test_pending_is_per_faculty(self):
        self.set_today(MON)
        _, pending = self.pending(self.sneha, MON)
        self.assertEqual([s.period_no for s in pending], [2])

    def test_holidays_and_sundays_are_never_pending(self):
        today = MON + datetime.timedelta(days=7)
        Holiday.objects.create(from_date=MON, to_date=MON, reason="Festival")
        _, pending = self.pending(self.ravi, today)
        self.assertEqual([s.date for s in pending], [today])

    def test_class_specific_holiday(self):
        from academics.models import SchoolClass
        Holiday.objects.create(from_date=MON, to_date=MON, reason="Class trip", school_class=self.c)
        todays, _ = self.pending(self.ravi, MON)
        self.assertEqual(todays, [])

    def test_lookback_window_is_limited(self):
        today = MON + datetime.timedelta(days=70)
        _, pending = self.pending(self.ravi, today)
        self.assertTrue(all((today - s.date).days <= 30 for s in pending))

    def test_home_screen_highlights_pending(self):
        today = MON + datetime.timedelta(days=7)
        self.set_today(today)
        self.client.force_login(self.ravi)
        r = self.client.get(reverse("faculty_home"))
        self.assertContains(r, "waiting for attendance")
        self.assertContains(r, "earlier days")
        mark(self, self.ravi, date=MON)
        mark(self, self.ravi, date=today)
        r = self.client.get(reverse("faculty_home"))
        self.assertNotContains(r, "waiting for attendance")
        self.assertContains(r, "Completed")


class TimetableVersionTests(AttendanceTestCase):
    def test_version_in_force_by_effective_date(self):
        new = Timetable.objects.create(school_class=self.c, effective_from=datetime.date(2026, 10, 6))
        from timetable.services import timetable_in_force
        self.assertEqual(timetable_in_force(self.c, MON), self.tt)      # before the new one starts
        self.assertEqual(timetable_in_force(self.c, TUE), new)
        self.assertIsNone(timetable_in_force(self.c, datetime.date(2026, 5, 1)))

    def test_new_version_does_not_change_past_records(self):
        self.set_today(MON)
        mark(self, self.ravi)
        # from Tuesday onward the class gets a new timetable where Monday P1 is Sneha's Databases
        new = Timetable.objects.create(school_class=self.c, effective_from=TUE)
        TimetableEntry.objects.create(timetable=new, day=0, period_no=1, start_time=at(9), end_time=at(10),
                                      subject=self.db, faculty=self.sneha)
        s = AttendanceSession.objects.get()
        self.assertEqual((s.subject, s.scheduled_faculty), (self.ds, self.ravi))
        index = svc.ScheduleIndex(MON, MON + datetime.timedelta(days=7))
        self.assertEqual(index.slots(MON, faculty_id=self.ravi.pk)[0].subject, self.ds)
        nxt = index.slots(MON + datetime.timedelta(days=7), class_id=self.c.pk)[0]
        self.assertEqual(nxt.entry.subject, self.db)
        self.assertFalse(nxt.completed)

    def test_editing_a_timetable_does_not_change_session_snapshot(self):
        self.set_today(MON)
        mark(self, self.ravi)
        self.e1.faculty = self.sneha
        self.e1.save()
        s = AttendanceSession.objects.get()
        self.assertEqual(s.scheduled_faculty, self.ravi)


class MonitoringAndAccessTests(AttendanceTestCase):
    def test_monitor_shows_entered_and_pending_with_faculty(self):
        self.set_today(MON)
        mark(self, self.ravi)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("monitor"), {"date": MON.isoformat()})
        self.assertContains(r, "1 entered")
        self.assertContains(r, "1 pending")
        self.assertContains(r, "Sneha")

    def test_monitor_holiday(self):
        Holiday.objects.create(from_date=MON, to_date=MON, reason="Festival")
        self.client.force_login(self.admin)
        r = self.client.get(reverse("monitor"), {"date": MON.isoformat()})
        self.assertContains(r, "holiday (Festival)")

    def test_faculty_cannot_open_monitor_or_timetable_pages(self):
        self.client.force_login(self.ravi)
        for url in (reverse("monitor"), reverse("timetable_list", args=[self.c.pk]),
                    reverse("timetable_grid", args=[self.tt.pk]), reverse("timetable_upload", args=[self.c.pk])):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_faculty_records_limited_to_own_subjects(self):
        self.set_today(MON)
        mark(self, self.ravi)
        mark(self, self.sneha, period=2)
        self.client.force_login(self.ravi)
        r = self.client.get(reverse("records"))
        self.assertContains(r, "Data Structures")
        self.assertNotContains(r, "Databases</div>")
        other = AttendanceSession.objects.get(period_no=2)
        self.assertEqual(self.client.get(reverse("session_detail", args=[other.pk])).status_code, 403)

    def test_admin_records_filter(self):
        self.set_today(MON)
        mark(self, self.ravi, topic="RAVI-TOPIC")
        mark(self, self.sneha, period=2, topic="SNEHA-TOPIC")
        self.client.force_login(self.admin)
        r = self.client.get(reverse("records"), {"faculty": self.sneha.pk})
        self.assertContains(r, "SNEHA-TOPIC")
        self.assertNotContains(r, "RAVI-TOPIC")
