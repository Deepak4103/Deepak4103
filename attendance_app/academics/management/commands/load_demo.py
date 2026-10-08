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
        Holiday.objects.get_or_create(from_date=datetime.date(2026, 10, 2), to_date=datetime.date(2026, 10, 2),
                                      defaults={"reason": "Gandhi Jayanti"})
        self.stdout.write(self.style.SUCCESS(
            f"Demo data loaded. Faculty logins: ravi / sneha / anil, password {DEMO_PASSWORD}"))
