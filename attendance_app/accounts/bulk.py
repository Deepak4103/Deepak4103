"""Bulk creation of faculty accounts from an Excel/CSV file."""
import secrets

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import User

HEADERS = ["full_name", "user_id", "password"]
_NAME_KEYS = ("full_name", "name", "faculty_name", "faculty")
_ID_KEYS = ("user_id", "userid", "username", "id")
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no look-alikes (0/O, 1/l/I)


def _first(row, keys):
    for k in keys:
        if row.get(k):
            return row[k].strip()
    return ""


def has_required_headers(headers):
    return bool(set(_NAME_KEYS) & set(headers)) and bool(set(_ID_KEYS) & set(headers))


def validate_rows(rows):
    """Split uploaded rows into (valid, errors).

    valid  = [{"full_name", "user_id", "password"}]  (password may be "" -> generated when saving)
    errors = [(line, user_id, full_name, message)]
    User IDs must be unique in the file and not already used by any account (any case)."""
    existing = {u.lower() for u in User.objects.values_list("username", flat=True)}
    username_field = User._meta.get_field("username")
    valid, errors, seen = [], [], set()
    for r in rows:
        line = r["_line"]
        name, uid, pw = _first(r, _NAME_KEYS), _first(r, _ID_KEYS), (r.get("password") or "").strip()
        problem = None
        if not name or not uid:
            problem = "Name and User ID are both required"
        elif len(uid) > username_field.max_length or any(ch.isspace() for ch in uid):
            problem = "User ID must have no spaces and at most 150 characters"
        else:
            try:
                username_field.run_validators(uid)
            except ValidationError:
                problem = "User ID may contain only letters, digits and @ . + - _"
        if not problem and uid.lower() in seen:
            problem = "Duplicate User ID in this file"
        if not problem and uid.lower() in existing:
            problem = "User ID already exists"
        if not problem and pw:
            try:
                password_validation.validate_password(pw)
            except ValidationError as exc:
                problem = "Password: " + " ".join(exc.messages)
        if problem:
            errors.append((line, uid, name, problem))
            continue
        seen.add(uid.lower())
        valid.append({"full_name": name, "user_id": uid, "password": pw})
    return valid, errors


def generate_password(length=8):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def create_accounts(valid):
    """Create the faculty accounts. Rows without a password get a random one. Everyone must change their
    password at first login. Returns [(full_name, user_id, password)] for the one-time results page."""
    created = []
    for v in valid:
        pw = v["password"] or generate_password()
        u = User(username=v["user_id"], full_name=v["full_name"], role=User.FACULTY, must_change_password=True)
        u.set_password(pw)
        u.save()
        created.append((v["full_name"], v["user_id"], pw))
    return created
