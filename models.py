"""Object-oriented layer: entities, validation and the manager classes from the proposal."""
from datetime import date, datetime

from werkzeug.security import check_password_hash, generate_password_hash

import db


class ValidationError(Exception):
    """Raised with a user-friendly message when input is not acceptable."""


class Status:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    ALL = [PENDING, APPROVED, REJECTED, COMPLETED]


DOCUMENT_TYPES = [
    "Barangay Clearance",
    "Certificate of Residency",
    "Certificate of Indigency",
    "Business Clearance",
]
CIVIL_STATUSES = ["Single", "Married", "Widowed", "Separated"]


# ---------------------------------------------------------------- users / auth
class User:
    ROLE_ADMIN = "ADMIN"
    ROLE_RESIDENT = "RESIDENT"

    def __init__(self, id, username, role, resident_id=None):
        self.id = id
        self.username = username
        self.role = role
        self.resident_id = resident_id

    @property
    def is_admin(self):
        return False

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        kind = Admin if row["role"] == cls.ROLE_ADMIN else User
        return kind(row["id"], row["username"], row["role"], row["resident_id"])

    @classmethod
    def get(cls, user_id):
        return cls.from_row(db.query("SELECT * FROM users WHERE id = %s", (user_id,), one=True))


class Admin(User):
    @property
    def is_admin(self):
        return True


class Auth:
    MIN_PASSWORD = 6

    @staticmethod
    def hash_password(password):
        return generate_password_hash(password)

    @classmethod
    def check_new_password(cls, password):
        if len(password) < cls.MIN_PASSWORD:
            raise ValidationError(f"Password must be at least {cls.MIN_PASSWORD} characters.")

    @staticmethod
    def authenticate(username, password):
        row = db.query("SELECT * FROM users WHERE username = %s", (username.strip(),), one=True)
        if row and check_password_hash(row["password_hash"], password):
            return User.from_row(row)
        return None

    @classmethod
    def create_account(cls, username, password, role, resident_id=None):
        username = username.strip()
        if len(username) < 3:
            raise ValidationError("Username must be at least 3 characters.")
        cls.check_new_password(password)
        if db.query("SELECT id FROM users WHERE username = %s", (username,), one=True):
            raise ValidationError("That username is already taken.")
        return db.execute(
            "INSERT INTO users (username, password_hash, role, resident_id) VALUES (%s, %s, %s, %s)",
            (username, cls.hash_password(password), role, resident_id),
        )

    @classmethod
    def change_password(cls, user_id, current, new, confirm):
        row = db.query("SELECT password_hash FROM users WHERE id = %s", (user_id,), one=True)
        if not row or not check_password_hash(row["password_hash"], current):
            raise ValidationError("Your current password is incorrect.")
        cls.check_new_password(new)
        if new != confirm:
            raise ValidationError("The new password and confirmation do not match.")
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (cls.hash_password(new), user_id))

    @classmethod
    def reset_resident_password(cls, resident_id, new):
        cls.check_new_password(new)
        row = db.query("SELECT id FROM users WHERE resident_id = %s", (resident_id,), one=True)
        if not row:
            raise ValidationError("This resident has no login account.")
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (cls.hash_password(new), row["id"]))


# ------------------------------------------------------------------- residents
class Resident:
    def __init__(self, full_name="", address="", birth_date=None, contact_number="",
                 civil_status="Single", id=None):
        self.id = id
        self.full_name = full_name.strip()
        self.address = address.strip()
        self.birth_date = birth_date
        self.contact_number = contact_number.strip()
        self.civil_status = civil_status

    @classmethod
    def from_form(cls, form, id=None):
        raw = (form.get("birth_date") or "").strip()
        try:
            birth = date.fromisoformat(raw) if raw else None
        except ValueError:
            raise ValidationError("Birth date is not a valid date.")
        return cls(form.get("full_name", ""), form.get("address", ""), birth,
                   form.get("contact_number", ""), form.get("civil_status", "Single"), id)

    @classmethod
    def from_row(cls, row):
        return cls(row["full_name"], row["address"], row["birth_date"], row["contact_number"] or "",
                   row["civil_status"] or "Single", row["id"])

    def validate(self):
        if not self.full_name:
            raise ValidationError("Full name is required.")
        if not self.address:
            raise ValidationError("Address is required.")
        if self.birth_date and self.birth_date >= date.today():
            raise ValidationError("Birth date must be in the past.")
        if self.civil_status not in CIVIL_STATUSES:
            raise ValidationError("Choose a valid civil status.")

    def as_form(self):
        return {
            "full_name": self.full_name, "address": self.address,
            "birth_date": self.birth_date.isoformat() if self.birth_date else "",
            "contact_number": self.contact_number, "civil_status": self.civil_status,
        }


class RecordManager:
    """CRUD for resident records."""

    @staticmethod
    def all():
        return db.query("SELECT r.*, u.username FROM residents r "
                        "LEFT JOIN users u ON u.resident_id = r.id ORDER BY r.full_name")

    @staticmethod
    def get(resident_id):
        row = db.query("SELECT * FROM residents WHERE id = %s", (resident_id,), one=True)
        return Resident.from_row(row) if row else None

    @staticmethod
    def create(resident):
        resident.validate()
        return db.execute(
            "INSERT INTO residents (full_name, address, birth_date, contact_number, civil_status) "
            "VALUES (%s, %s, %s, %s, %s)",
            (resident.full_name, resident.address, resident.birth_date,
             resident.contact_number, resident.civil_status))

    @staticmethod
    def update(resident):
        resident.validate()
        db.execute(
            "UPDATE residents SET full_name=%s, address=%s, birth_date=%s, contact_number=%s, "
            "civil_status=%s WHERE id=%s",
            (resident.full_name, resident.address, resident.birth_date,
             resident.contact_number, resident.civil_status, resident.id))

    @staticmethod
    def delete(resident_id):
        # requests, appointments and the login account are removed by ON DELETE CASCADE
        db.execute("DELETE FROM residents WHERE id = %s", (resident_id,))


# -------------------------------------------------------------------- requests
class Request:
    """Base class for anything a resident asks the barangay for."""

    @staticmethod
    def check_status(status):
        if status not in Status.ALL:
            raise ValidationError("Invalid status.")


class DocumentRequest(Request):
    def __init__(self, resident_id, document_type, purpose):
        self.resident_id = resident_id
        self.document_type = document_type
        self.purpose = purpose.strip()

    def validate(self):
        if self.document_type not in DOCUMENT_TYPES:
            raise ValidationError("Choose a valid document type.")
        if not self.purpose:
            raise ValidationError("Purpose is required.")


class RequestManager:
    @staticmethod
    def create(doc_request):
        doc_request.validate()
        return db.execute(
            "INSERT INTO document_requests (resident_id, document_type, purpose) VALUES (%s, %s, %s)",
            (doc_request.resident_id, doc_request.document_type, doc_request.purpose))

    @staticmethod
    def for_resident(resident_id):
        return db.query("SELECT * FROM document_requests WHERE resident_id = %s "
                        "ORDER BY created_at DESC", (resident_id,))

    @staticmethod
    def all():
        return db.query("SELECT d.*, r.full_name FROM document_requests d "
                        "JOIN residents r ON r.id = d.resident_id ORDER BY d.created_at DESC")

    @staticmethod
    def set_status(request_id, status, remarks):
        Request.check_status(status)
        db.execute("UPDATE document_requests SET status = %s, remarks = %s WHERE id = %s",
                   (status, (remarks or "").strip() or None, request_id))


# ---------------------------------------------------------------- appointments
class Appointment:
    def __init__(self, resident_id, purpose, scheduled_at):
        self.resident_id = resident_id
        self.purpose = purpose.strip()
        self.scheduled_at = scheduled_at

    @classmethod
    def from_form(cls, resident_id, form):
        raw = (form.get("scheduled_at") or "").strip()
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            raise ValidationError("Choose a valid date and time.")
        return cls(resident_id, form.get("purpose", ""), when)

    def validate(self):
        if not self.purpose:
            raise ValidationError("Purpose is required.")
        if self.scheduled_at <= datetime.now():
            raise ValidationError("The appointment must be in the future.")


class AppointmentManager:
    @staticmethod
    def create(appointment):
        appointment.validate()
        return db.execute(
            "INSERT INTO appointments (resident_id, purpose, scheduled_at) VALUES (%s, %s, %s)",
            (appointment.resident_id, appointment.purpose, appointment.scheduled_at))

    @staticmethod
    def for_resident(resident_id):
        return db.query("SELECT * FROM appointments WHERE resident_id = %s "
                        "ORDER BY scheduled_at", (resident_id,))

    @staticmethod
    def all():
        return db.query("SELECT a.*, r.full_name FROM appointments a "
                        "JOIN residents r ON r.id = a.resident_id ORDER BY a.scheduled_at")

    @staticmethod
    def set_status(appointment_id, status):
        Request.check_status(status)
        db.execute("UPDATE appointments SET status = %s WHERE id = %s", (status, appointment_id))


# ------------------------------------------------------------ dashboard/report
class Dashboard:
    """What a resident sees after logging in."""

    def __init__(self, resident):
        self.resident = resident
        self.requests = RequestManager.for_resident(resident.id)
        self.appointments = AppointmentManager.for_resident(resident.id)


class Report:
    def __init__(self, residents, requests_by_status, appointments_by_status):
        self.residents = residents
        self.requests_by_status = requests_by_status
        self.appointments_by_status = appointments_by_status
        self.total_requests = sum(requests_by_status.values())
        self.total_appointments = sum(appointments_by_status.values())


class ReportGenerator:
    @staticmethod
    def _counts(table):
        rows = db.query(f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status")
        counts = {s: 0 for s in Status.ALL}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    @classmethod
    def generate(cls):
        residents = db.query("SELECT COUNT(*) AS n FROM residents", one=True)["n"]
        return Report(residents, cls._counts("document_requests"), cls._counts("appointments"))
