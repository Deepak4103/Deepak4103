import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from academics.models import Allotment, SchoolClass, Student, Subject
from accounts.models import User
from leaves.models import LeaveType
from timetable.models import Timetable, TimetableEntry

SAT = datetime.date(2026, 10, 3)
SUN = datetime.date(2026, 10, 4)
MON = datetime.date(2026, 10, 5)
TUE = datetime.date(2026, 10, 6)
WED = datetime.date(2026, 10, 7)
TODAY = SUN


def at(h):
    return datetime.time(h, 0)


class LeaveTestCase(TestCase):
    """Class A: DS (Ravi), DB (Sneha).  Class B: DS (Dev - same subject elsewhere), PH (Anil - unrelated).
    Mon timetable  A: P1 DS Ravi, P2 DB Sneha, P3 DS Ravi, P4 DB Sneha     B: P1 PH Anil, P2 DS Dev, P3 PH Anil
    Tue timetable  A: P1 DS Ravi."""

    def setUp(self):
        mk = lambda uid, name, role=User.FACULTY, **kw: User.objects.create_user(
            uid, password="pw123456", full_name=name, role=role, **kw)
        self.admin = mk("adm", "Admin", User.ADMIN)
        self.ravi, self.sneha, self.dev, self.anil = (mk("ravi", "Ravi"), mk("sneha", "Sneha"),
                                                      mk("dev", "Dev"), mk("anil", "Anil"))
        self.A = SchoolClass.objects.create(name="A", branch="CSE", year=2, semester=1, section="A")
        self.B = SchoolClass.objects.create(name="B", branch="CSE", year=2, semester=1, section="B")
        for i in range(1, 4):
            Student.objects.create(school_class=self.A, roll_no=f"A{i}", name=f"A student {i}")
        for i in range(1, 3):
            Student.objects.create(school_class=self.B, roll_no=f"B{i}", name=f"B student {i}")
        self.A_ds = Subject.objects.create(school_class=self.A, name="Data Structures", code="DS")
        self.A_db = Subject.objects.create(school_class=self.A, name="Databases", code="DB")
        self.B_ds = Subject.objects.create(school_class=self.B, name="Data Structures", code="DS")
        self.B_ph = Subject.objects.create(school_class=self.B, name="Physics", code="PH")
        for s, f in ((self.A_ds, self.ravi), (self.A_db, self.sneha), (self.B_ds, self.dev), (self.B_ph, self.anil)):
            Allotment.objects.create(subject=s, faculty=f)
        self.ttA = Timetable.objects.create(school_class=self.A, effective_from=datetime.date(2026, 9, 1))
        self.ttB = Timetable.objects.create(school_class=self.B, effective_from=datetime.date(2026, 9, 1))
        for day, p, s, f in ((0, 1, self.A_ds, self.ravi), (0, 2, self.A_db, self.sneha), (0, 3, self.A_ds, self.ravi),
                             (0, 4, self.A_db, self.sneha), (1, 1, self.A_ds, self.ravi)):
            self.entry(self.ttA, day, p, s, f)
        for day, p, s, f in ((0, 1, self.B_ph, self.anil), (0, 2, self.B_ds, self.dev), (0, 3, self.B_ph, self.anil)):
            self.entry(self.ttB, day, p, s, f)
        self.casual = LeaveType.objects.create(name="Casual Leave", days_per_year=Decimal("12.0"))
        self.set_today(TODAY)

    def entry(self, tt, day, p, subject, faculty):
        return TimetableEntry.objects.create(timetable=tt, day=day, period_no=p, start_time=at(8 + p),
                                             end_time=at(9 + p), subject=subject, faculty=faculty)

    def set_today(self, date):
        for target in ("attendance.services.today", "leaves.services.today", "leaves.views.today"):
            p = mock.patch(target, return_value=date)
            p.start()
            self.addCleanup(p.stop)
