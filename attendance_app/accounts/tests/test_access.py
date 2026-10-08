from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User


class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("adm", password="pw123456", full_name="Admin", role=User.ADMIN)
        cls.fac = User.objects.create_user("fac", password="pw123456", full_name="Fac", role=User.FACULTY)

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_passwords_are_hashed_with_pbkdf2(self):
        # (the rest of the test-suite uses a fast hasher; production uses Django's default PBKDF2)
        user = User.objects.create_user("hashcheck", password="pw123456", full_name="H", role=User.FACULTY)
        self.assertNotEqual(user.password, "pw123456")
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password("pw123456"))

    def test_anonymous_redirected_to_login(self):
        for name in ["admin_home", "class_list", "faculty_list", "holiday_list", "faculty_home"]:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login/", r["Location"])

    def test_faculty_cannot_open_admin_pages(self):
        self.client.force_login(self.fac)
        for name in ["admin_home", "class_list", "faculty_list", "faculty_add", "holiday_list", "class_add"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_admin_cannot_open_faculty_home(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("faculty_home")).status_code, 403)

    def test_home_redirects_by_role(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get("/"), reverse("admin_home"))
        self.client.force_login(self.fac)
        self.assertRedirects(self.client.get("/"), reverse("faculty_home"))

    def test_logout_returns_to_the_login_page(self):
        for user in (self.admin, self.fac):
            self.client.force_login(user)
            r = self.client.post(reverse("logout"))
            self.assertRedirects(r, reverse("login"))
            self.assertEqual(self.client.get(reverse("home")).status_code, 302)     # really logged out

    def test_deactivated_faculty_cannot_login(self):
        self.fac.is_active = False
        self.fac.save()
        self.assertFalse(self.client.login(username="fac", password="pw123456"))

    def test_forced_password_change(self):
        self.fac.must_change_password = True
        self.fac.save()
        self.client.force_login(self.fac)
        self.assertRedirects(self.client.get(reverse("faculty_home")), reverse("password_change"))
        r = self.client.post(reverse("password_change"), {
            "old_password": "pw123456", "new_password1": "NewPass#9876", "new_password2": "NewPass#9876"})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
        self.fac.refresh_from_db()
        self.assertFalse(self.fac.must_change_password)
        self.assertEqual(self.client.get(reverse("faculty_home")).status_code, 200)


class FacultyAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", password="pw123456", full_name="Admin", role=User.ADMIN)
        self.client.force_login(self.admin)

    def test_create_reset_deactivate(self):
        self.client.post(reverse("faculty_add"), {"full_name": "New Fac", "username": "newfac", "password": "secret123"})
        f = User.objects.get(username="newfac")
        self.assertEqual(f.role, User.FACULTY)
        self.assertTrue(f.check_password("secret123"))
        self.client.post(reverse("faculty_reset_password", args=[f.pk]), {"new_password": "another456", "force_change": "on"})
        f.refresh_from_db()
        self.assertTrue(f.check_password("another456"))
        self.assertTrue(f.must_change_password)
        self.client.post(reverse("faculty_toggle_active", args=[f.pk]))
        f.refresh_from_db()
        self.assertFalse(f.is_active)

    def test_duplicate_user_id_rejected(self):
        r = self.client.post(reverse("faculty_add"), {"full_name": "X", "username": "adm", "password": "secret123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.filter(username="adm").count(), 1)
