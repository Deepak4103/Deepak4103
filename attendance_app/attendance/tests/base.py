import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from academics.models import Allotment, SchoolClass, Student, Subject
from accounts.models import User
from timetable.models import Timetable, TimetableEntry

MON = datetime.date(2026, 10, 5)       # a Monday
TUE = datetime.date(2026, 10, 6)
WED = datetime.date(2026, 10, 7)
SUN = datetime.date(2026, 10, 4)


def at(h, m=0):
    return datetime.time(h, m)


class AttendanceTestCase(TestCase):
    """A class with 4 students, 2 subjects/faculty and a timetable: Mon P1 = DS (ravi), Mon P2 = DB (sneha)."""

    def setUp(self):
        self.admin = User.objects.create_user("adm", password="pw123456", full_name="Admin", role=User.ADMIN)
        self.ravi = User.objects.create_user("ravi", password="pw123456", full_name="Ravi", role=User.FACULTY)
        self.sneha = User.objects.create_user("sneha", password="pw123456", full_name="Sneha", role=User.FACULTY)
        self.c = SchoolClass.objects.create(name="A", branch="CSE", year=2, semester=1, section="A")
        self.students = [Student.objects.create(school_class=self.c, roll_no=f"R{i}", name=f"S{i}") for i in range(1, 5)]
        self.ds = Subject.objects.create(school_class=self.c, name="Data Structures", code="DS")
        self.db = Subject.objects.create(school_class=self.c, name="Databases", code="DB")
        Allotment.objects.create(subject=self.ds, faculty=self.ravi)
        Allotment.objects.create(subject=self.db, faculty=self.sneha)
        self.tt = Timetable.objects.create(school_class=self.c, effective_from=MON)
        self.e1 = TimetableEntry.objects.create(timetable=self.tt, day=0, period_no=1, start_time=at(9), end_time=at(10),
                                                subject=self.ds, faculty=self.ravi)
        self.e2 = TimetableEntry.objects.create(timetable=self.tt, day=0, period_no=2, start_time=at(10), end_time=at(11),
                                                subject=self.db, faculty=self.sneha)

    def set_today(self, date):
        p = mock.patch("attendance.services.today", return_value=date)
        p.start()
        self.addCleanup(p.stop)

    def set_entered_on(self, session, date):
        """Pretend the record was first saved on `date`."""
        dt = timezone.make_aware(datetime.datetime.combine(date, at(12)))
        type(session).objects.filter(pk=session.pk).update(created_at=dt)
        session.refresh_from_db()
