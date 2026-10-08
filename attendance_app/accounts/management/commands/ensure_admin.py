import os

from django.core.management.base import BaseCommand

from accounts.models import User

DEFAULT_ADMIN_ID = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@12345"


class Command(BaseCommand):
    help = "Create the default admin account if no admin exists."

    def handle(self, *args, **options):
        if User.objects.filter(role=User.ADMIN).exists():
            self.stdout.write("An admin account already exists; nothing to do.")
            return
        user_id = os.environ.get("ADMIN_USER_ID", DEFAULT_ADMIN_ID)
        password = os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
        User.objects.create_user(
            username=user_id, password=password, full_name="Administrator", role=User.ADMIN,
            is_staff=True, is_superuser=True, must_change_password=True,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Default admin created. User ID: {user_id}  Password: {password}  (must be changed at first login)"))
