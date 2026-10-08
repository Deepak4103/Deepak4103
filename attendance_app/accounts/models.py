from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """`username` is the login User ID. Passwords are hashed by Django (PBKDF2)."""
    ADMIN = "admin"
    FACULTY = "faculty"
    ROLE_CHOICES = [(ADMIN, "Admin"), (FACULTY, "Faculty")]

    full_name = models.CharField(max_length=120)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=FACULTY)
    must_change_password = models.BooleanField(default=False)

    first_name = None
    last_name = None
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]

    @property
    def is_admin_role(self):
        return self.role == self.ADMIN

    @property
    def is_faculty_role(self):
        return self.role == self.FACULTY

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name

    def __str__(self):
        return self.full_name or self.username
