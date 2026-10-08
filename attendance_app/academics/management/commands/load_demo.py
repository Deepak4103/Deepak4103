import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import Allotment, Holiday, SchoolClass, Student, Subject
from accounts.models import User

FACULTY = [("ravi", "Dr. Ravi Kumar"), ("sneha", "Prof. Sneha Reddy"), ("anil", "Mr. Anil Sharma")]
DEMO_PASSWORD = "Faculty@123"

CLASSES = [
    # (branch, year, sem, section, name, roll prefix, [(subject, code, faculty id)])
    ("CSE", 2, 1, "A", "CSE-2-1-A", "21CSEA", [
        ("Data Structures", "CS201", "ravi"), ("Database Systems", "CS202", "sneha"),
        ("Operating Systems", "CS203", "anil")]),
    ("CSE", 2, 1, "B", "CSE-2-1-B", "21CSEB", [
        ("Data Structures", "CS201", "ravi"), ("Database Systems", "CS202", "sneha"),
        ("Operating Systems", "CS203", "anil")]),
]
NAMES = ["Asha Rao", "Bharat Singh", "Chitra Nair", "Deepa Menon", "Eshan Gupta",
         "Farah Khan", "Gopal Das", "Harini Iyer", "Imran Ali", "Jaya Patel"]


class Command(BaseCommand):
    help = "Load sample data (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("ensure_admin")
        fac = {}
        for uid, name in FACULTY:
            u, created = User.objects.get_or_create(username=uid, defaults={"full_name": name, "role": User.FACULTY})
            if created:
                u.set_password(DEMO_PASSWORD)
                u.save()
            fac[uid] = u
        for branch, year, sem, sec, name, prefix, subjects in CLASSES:
            c, _ = SchoolClass.objects.get_or_create(
                branch=branch, year=year, semester=sem, section=sec, defaults={"name": name})
            for i, n in enumerate(NAMES, 1):
                Student.objects.get_or_create(roll_no=f"{prefix}{i:02d}", defaults={"school_class": c, "name": n})
            for sname, code, f in subjects:
                s, _ = Subject.objects.get_or_create(school_class=c, code=code, defaults={"name": sname})
                Allotment.objects.get_or_create(subject=s, defaults={"faculty": fac[f]})
        import datetime

        from attendance.services import today
        self.start = today() - datetime.timedelta(days=9)      # demo timetable starts 9 days ago
        holiday = today() - datetime.timedelta(days=6)
        Holiday.objects.get_or_create(from_date=holiday, to_date=holiday, defaults={"reason": "Festival holiday"})
        self._timetables(fac)
        self._attendance()
        self._leave(fac)
        self.stdout.write(self.style.SUCCESS(
            f"Demo data loaded. Faculty logins: ravi / sneha / anil, password {DEMO_PASSWORD}"))

    TIMES = [("09:00", "09:50"), ("09:50", "10:40"), ("10:50", "11:40"), ("11:40", "12:30"),
             ("13:30", "14:20"), ("14:20", "15:10"), ("15:10", "16:00")]

    def _timetables(self, fac):
        """Mon-Sat, periods 1-6 filled (period 7 free). Class B is the class A pattern shifted by one subject,
        so no teacher is ever in two classes at the same time."""
        from datetime import time

        from timetable.models import Timetable, TimetableEntry
        for offset, section in ((0, "A"), (1, "B")):
            c = SchoolClass.objects.get(branch="CSE", year=2, semester=1, section=section)
            subjects = list(c.subjects.order_by("code"))
            tt, created = Timetable.objects.get_or_create(school_class=c, effective_from=self.start)
            if not created:
                continue
            rows = []
            for day in range(6):
                for p in range(1, 7):
                    s = subjects[(day + p + offset) % 3]
                    start, end = self.TIMES[p - 1]
                    rows.append(TimetableEntry(
                        timetable=tt, day=day, period_no=p, subject=s, faculty=s.allotment.faculty,
                        start_time=time.fromisoformat(start), end_time=time.fromisoformat(end)))
            TimetableEntry.objects.bulk_create(rows)

    def _attendance(self):
        """Fill attendance for the last few working days so reports have data. Some periods are left pending."""
        import datetime

        from attendance import services as svc
        from attendance.models import AttendanceSession
        if AttendanceSession.objects.exists():
            return
        today = svc.today()
        index = svc.ScheduleIndex(self.start, today)
        days = []                                  # working days since the timetable began, newest first
        d = today - datetime.timedelta(days=1)
        while d >= self.start:
            if not index.holiday_reason(d, None):
                days.append(d)
            d -= datetime.timedelta(days=1)
        topics = ["Introduction", "Core concepts", "Worked examples", "Problem solving", "Revision"]
        for n, day in enumerate(reversed(days)):
            for slot in index.slots(day):
                if day == days[0] and slot.period_no >= 5:
                    continue                                    # leave the latest day's afternoon pending
                students = list(slot.school_class.students.all())
                absent = {s.pk for i, s in enumerate(students) if (i * 7 + slot.period_no + n) % 9 == 0}
                svc.save_attendance(
                    school_class=slot.school_class, date=day, period_no=slot.period_no, entry=slot.entry,
                    user=slot.entry.faculty, absent_ids=absent,
                    topic=f"{slot.entry.subject.name}: {topics[n % len(topics)]}")
        # today: first two periods already entered
        for slot in index.slots(today):
            if slot.period_no <= 2:
                svc.save_attendance(school_class=slot.school_class, date=today, period_no=slot.period_no,
                                    entry=slot.entry, user=slot.entry.faculty, absent_ids=set(),
                                    topic=f"{slot.entry.subject.name}: Introduction")

    def _leave(self, fac):
        """Leave types, and one approved leave (Ravi, two periods) with a substitute for each period."""
        from attendance import services as svc
        from leaves import services as leave_svc
        from leaves.models import LeaveRequest, LeaveType
        for name, days in (("Casual Leave", 12), ("Medical Leave", 10), ("Earned Leave", 15), ("On Duty", 10)):
            LeaveType.objects.get_or_create(name=name, defaults={"days_per_year": days})
        if LeaveRequest.objects.exists():
            return
        admin = User.objects.get(role=User.ADMIN)
        today = svc.today()
        day = today
        index = svc.ScheduleIndex(today, today + datetime.timedelta(days=10))
        while not [s for s in index.slots(day, faculty_id=fac["ravi"].pk) if not s.completed]:
            day += datetime.timedelta(days=1)
        mine = [s for s in index.slots(day, faculty_id=fac["ravi"].pk) if not s.completed]
        periods = sorted({s.period_no for s in mine})[-2:]
        req = leave_svc.create_leave_request(
            faculty=fac["ravi"], leave_type=LeaveType.objects.get(name="Casual Leave"), from_date=day, to_date=day,
            scope="periods", periods=",".join(map(str, periods)), reason="Family function", created_by=admin)
        ctx = leave_svc.DayContext(day)
        for n, adj in enumerate(leave_svc.leave_adjustments(req)):
            options = leave_svc.eligible_faculty(adj.school_class, adj.original_subject, day, adj.period_no,
                                                 original_faculty=fac["ravi"], ctx=ctx)
            if not options:
                continue
            sub = options[0]
            others = [s for s in adj.school_class.subjects.all() if s.pk != adj.original_subject_id]
            different = n % 2 == 0 and others                  # first one teaches a different subject
            leave_svc.set_adjustment(adj, user=admin, substitute=sub, same_subject=not different,
                                     subject=others[0] if different else None)
