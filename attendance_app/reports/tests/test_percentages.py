import datetime

from academics.models import Student, set_setting
from reports import stats
from reports.stats import Filters, below, pct

from .base import ReportTestCase, week


def f(**kw):
    kw.setdefault("school_class", None)
    return Filters(**kw)


class PercentageMathTests(ReportTestCase):
    def test_pct_rounds_to_one_decimal_and_handles_zero(self):
        self.assertEqual(pct(3, 4), 75.0)
        self.assertEqual(pct(2, 3), 66.7)
        self.assertEqual(pct(0, 5), 0.0)
        self.assertIsNone(pct(0, 0))

    def test_threshold_is_strictly_below(self):
        self.assertFalse(below(3, 4, 75))        # exactly 75% is not a shortage
        self.assertTrue(below(2, 3, 75))
        self.assertTrue(below(149, 200, 75))     # 74.5 - not rounded up to 75
        self.assertFalse(below(0, 0, 75))        # nothing held yet

    def test_attendance_is_held_attended_over_classes_actually_held(self):
        for i in range(4):
            self.held(week(i), absent=[self.r(1)] if i == 0 else [])
        counts = stats.student_totals(f(school_class=self.c))
        self.assertEqual(counts[self.r(1).pk], (4, 3))          # 75.0%
        self.assertEqual(counts[self.r(2).pk], (4, 4))

    def test_timetable_is_never_used_as_the_denominator(self):
        # Timetable has Monday P1 every week, but only two were actually held.
        self.held(week(0))
        self.held(week(1), absent=[self.r(1)])
        self.assertEqual(stats.student_totals(f())[self.r(1).pk], (2, 1))

    def test_grouped_by_subject_actually_taught_not_the_timetable_subject(self):
        self.held(week(0))                                              # DS as timetabled
        self.adjusted(week(1), taught=self.db, absent=[self.r(1)])      # timetable says DS, DB was taught
        by = stats.student_subject_counts(f(school_class=self.c))
        self.assertEqual(by[(self.r(1).pk, self.ds.pk)], (1, 1))
        self.assertEqual(by[(self.r(1).pk, self.db.pk)], (1, 0))
        self.assertEqual(stats.student_totals(f())[self.r(1).pk], (2, 1))

    def test_same_subject_adjustment_counts_under_the_original_subject(self):
        self.adjusted(week(0), same=True)
        self.assertEqual(list(stats.student_subject_counts(f()))[0][1], self.ds.pk)

    def test_subject_filter_matches_the_subject_taught(self):
        self.held(week(0))
        self.adjusted(week(1), taught=self.db)
        self.assertEqual(stats.student_totals(f(subject_code="ds"))[self.r(1).pk], (1, 1))
        self.assertEqual(stats.student_totals(f(subject_code="DB"))[self.r(1).pk], (1, 1))

    def test_date_range_is_inclusive(self):
        for i in range(4):
            self.held(week(i), absent=[self.r(1)] if i == 3 else [])
        self.assertEqual(stats.student_totals(f(date_from=week(1), date_to=week(2)))[self.r(1).pk], (2, 2))
        self.assertEqual(stats.student_totals(f(date_from=week(3)))[self.r(1).pk], (1, 0))
        self.assertEqual(stats.student_totals(f(date_to=week(0)))[self.r(1).pk], (1, 1))

    def test_student_added_later_is_not_penalised_for_earlier_periods(self):
        self.held(week(0))
        late = Student.objects.create(school_class=self.c, roll_no="R9", name="Late joiner")
        self.held(week(1))
        self.assertEqual(stats.student_totals(f())[late.pk], (1, 1))
        self.assertEqual(stats.student_totals(f())[self.r(1).pk], (2, 2))

    def test_faculty_filter_uses_the_person_credited_with_the_period(self):
        self.held(week(0), user=self.ravi)                              # Ravi's own
        self.adjusted(week(1), substitute=self.sneha, taught=self.db)   # credited to Sneha
        self.assertEqual(stats.student_totals(f(faculty=self.ravi))[self.r(1).pk], (1, 1))
        self.assertEqual(stats.student_totals(f(faculty=self.sneha))[self.r(1).pk], (1, 1))

    def test_class_filter(self):
        self.held(week(0))
        from academics.models import SchoolClass
        other = SchoolClass.objects.create(name="B", branch="CSE", year=2, semester=1, section="B")
        self.assertEqual(stats.student_totals(f(school_class=other)), {})

    def test_student_with_no_classes_held_has_no_percentage(self):
        self.assertEqual(stats.student_totals(f()), {})


class ShortageTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        # R1 3/4 = 75.0%, R2 2/4 = 50%, R3 4/4, R4 3/4
        self.held(week(0), absent=[self.r(2)])
        self.held(week(1), absent=[self.r(2)])
        self.held(week(2), absent=[self.r(1)])
        self.held(week(3), absent=[self.r(4)])

    def rows(self, **kw):
        from reports.builders import shortage
        return shortage(f(**kw)).rows

    def test_default_threshold_is_75_and_exactly_75_is_not_short(self):
        rows = self.rows()
        self.assertEqual([r[1] for r in rows], ["R2"])
        self.assertEqual(rows[0][3:6], [4, 2, "50.0%"])

    def test_admin_can_edit_the_threshold(self):
        set_setting("shortage_threshold", 80)
        self.assertEqual([r[1] for r in self.rows()], ["R2", "R1", "R4"])      # lowest first, ties by roll no

    def test_threshold_can_be_overridden_on_the_report(self):
        self.assertEqual({r[1] for r in self.rows(threshold=51)}, {"R2"})
        self.assertEqual({r[1] for r in self.rows(threshold=76)}, {"R1", "R2", "R4"})
        self.assertEqual(self.rows(threshold=50), [])

    def test_lowest_first(self):
        set_setting("shortage_threshold", 80)
        self.assertEqual([r[1] for r in self.rows()][0], "R2")

    def test_date_range_changes_who_is_short(self):
        self.assertEqual({r[1] for r in self.rows()}, {"R2"})                       # whole term
        self.assertEqual({r[1] for r in self.rows(date_from=week(2))}, {"R1", "R4"})  # last two periods only
        self.assertEqual({r[1] for r in self.rows(date_from=week(3))}, {"R4"})
        self.assertEqual({r[1] for r in self.rows(date_to=week(0))}, {"R2"})

    def test_subject_filter_uses_only_that_subject(self):
        self.held(week(0), period=2, absent=[self.r(3)])               # a single DB period, R3 absent
        self.assertEqual({r[1] for r in self.rows(subject_code="DB")}, {"R3"})
        self.assertEqual({r[1] for r in self.rows(subject_code="DS")}, {"R2"})

    def test_lists_subjects_below_threshold(self):
        self.held(week(0), period=2, absent=[self.r(2)])
        row = next(r for r in self.rows() if r[1] == "R2")
        self.assertIn("Data Structures 50.0%", row[6])
        self.assertIn("Databases 0.0%", row[6])

    def test_setting_default_and_validation(self):
        from academics.models import shortage_threshold
        set_setting("shortage_threshold", 75)
        self.assertEqual(shortage_threshold(), 75)
