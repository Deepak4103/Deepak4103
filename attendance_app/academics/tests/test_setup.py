import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from academics.models import Allotment, Holiday, SchoolClass, Student, Subject, is_holiday
from academics.views import validate_student_rows
from accounts.models import User


def make_class(section="A"):
    return SchoolClass.objects.create(name=f"CSE-2-{section}", branch="CSE", year=2, semester=1, section=section)


class AdminTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", password="pw123456", full_name="Admin", role=User.ADMIN)
        self.client.force_login(self.admin)


class StudentTests(AdminTestCase):
    def test_roll_number_unique_across_classes(self):
        a, b = make_class("A"), make_class("B")
        Student.objects.create(school_class=a, roll_no="r1", name="One")
        r = self.client.post(reverse("student_add", args=[b.pk]), {"roll_no": " R1 ", "name": "Other"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already exists")
        self.assertEqual(Student.objects.count(), 1)

    def test_roll_numbers_normalised(self):
        c = make_class()
        s = Student.objects.create(school_class=c, roll_no=" 21cse01 ", name=" X ")
        self.assertEqual((s.roll_no, s.name), ("21CSE01", "X"))

    def test_validate_rows_flags_problems(self):
        c = make_class()
        Student.objects.create(school_class=c, roll_no="A1", name="Existing")
        rows = [{"_line": 2, "roll_no": "a1", "name": "Dup of db"},
                {"_line": 3, "roll_no": "B1", "name": "Fine"},
                {"_line": 4, "roll_no": "b1", "name": "Dup in file"},
                {"_line": 5, "roll_no": "", "name": "No roll"}]
        valid, errors = validate_student_rows(rows)
        self.assertEqual(valid, [{"roll_no": "B1", "name": "Fine"}])
        self.assertEqual([e[0] for e in errors], [2, 4, 5])

    def test_csv_upload_preview_then_confirm(self):
        c = make_class()
        csv = SimpleUploadedFile("s.csv", b"Roll No,Name\nX1,Ann\nX2,Bob\nX1,Ann again\n")
        r = self.client.post(reverse("student_upload", args=[c.pk]), {"file": csv})
        self.assertContains(r, "2 will be added")
        self.assertEqual(Student.objects.count(), 0)  # nothing saved by preview
        self.client.post(reverse("student_upload", args=[c.pk]), {"action": "confirm"})
        self.assertEqual(sorted(Student.objects.values_list("roll_no", flat=True)), ["X1", "X2"])

    def test_xlsx_upload(self):
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.append(["roll_no", "name"])
        wb.active.append(["Y1", "Cat"])
        buf = io.BytesIO()
        wb.save(buf)
        c = make_class()
        f = SimpleUploadedFile("s.xlsx", buf.getvalue())
        r = self.client.post(reverse("student_upload", args=[c.pk]), {"file": f})
        self.assertContains(r, "1 will be added")

    def test_bad_header_rejected(self):
        c = make_class()
        r = self.client.post(reverse("student_upload", args=[c.pk]),
                             {"file": SimpleUploadedFile("s.csv", b"a,b\n1,2\n")})
        self.assertContains(r, "Header row must contain")


class SubjectAllotmentTests(AdminTestCase):
    def test_subject_code_unique_per_class_only(self):
        a, b = make_class("A"), make_class("B")
        Subject.objects.create(school_class=a, name="DS", code="cs1")
        r = self.client.post(reverse("subject_add", args=[a.pk]), {"name": "DS2", "code": "CS1"})
        self.assertContains(r, "already has a subject")
        r = self.client.post(reverse("subject_add", args=[b.pk]), {"name": "DS", "code": "CS1"})
        self.assertEqual(r.status_code, 302)

    def test_allotment_save_and_clear(self):
        c = make_class()
        s = Subject.objects.create(school_class=c, name="DS", code="CS1")
        f = User.objects.create_user("f1", password="x", full_name="F1", role=User.FACULTY)
        self.client.post(reverse("allotment", args=[c.pk]), {f"subject_{s.pk}": str(f.pk)})
        s.refresh_from_db()
        self.assertEqual(s.allotment.faculty, f)
        self.client.post(reverse("allotment", args=[c.pk]), {f"subject_{s.pk}": ""})
        self.assertFalse(Allotment.objects.filter(subject=s).exists())

    def test_admin_cannot_allot_to_admin_or_inactive(self):
        c = make_class()
        s = Subject.objects.create(school_class=c, name="DS", code="CS1")
        self.client.post(reverse("allotment", args=[c.pk]), {f"subject_{s.pk}": str(self.admin.pk)})
        self.assertFalse(hasattr(Subject.objects.get(pk=s.pk), "allotment"))


class HolidayTests(AdminTestCase):
    def test_sunday_is_holiday(self):
        self.assertTrue(is_holiday(datetime.date(2026, 10, 4)))   # Sunday
        self.assertFalse(is_holiday(datetime.date(2026, 10, 5)))  # Monday

    def test_college_and_class_holidays(self):
        a, b = make_class("A"), make_class("B")
        Holiday.objects.create(from_date=datetime.date(2026, 10, 6), to_date=datetime.date(2026, 10, 7), reason="All")
        Holiday.objects.create(from_date=datetime.date(2026, 10, 8), to_date=datetime.date(2026, 10, 8),
                               reason="A only", school_class=a)
        self.assertTrue(is_holiday(datetime.date(2026, 10, 7), b))
        self.assertTrue(is_holiday(datetime.date(2026, 10, 8), a))
        self.assertFalse(is_holiday(datetime.date(2026, 10, 8), b))

    def test_end_before_start_rejected(self):
        r = self.client.post(reverse("holiday_add"), {"from_date": "2026-10-10", "to_date": "2026-10-09", "reason": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Holiday.objects.count(), 0)


class ClassTests(AdminTestCase):
    def test_duplicate_class_rejected(self):
        make_class("A")
        r = self.client.post(reverse("class_add"), {"name": "dup", "branch": "CSE", "year": 2, "semester": 1, "section": "A"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SchoolClass.objects.count(), 1)

    def test_delete_class_cascades(self):
        c = make_class()
        Student.objects.create(school_class=c, roll_no="Z1", name="Z")
        self.client.post(reverse("class_delete", args=[c.pk]))
        self.assertEqual(Student.objects.count(), 0)
