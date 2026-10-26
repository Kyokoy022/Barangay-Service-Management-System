"""Barangay Service Management System - Flask web app."""
import os
import secrets
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup

import db
from models import (CIVIL_STATUSES, DOCUMENT_TYPES, Appointment, AppointmentManager,
                    Auth, Dashboard, DocumentRequest, RecordManager, ReportGenerator,
                    RequestManager, Resident, Status, User, ValidationError)


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    )
    app.teardown_appcontext(db.close_db)
    db.init_db(Auth.hash_password)

    # ----------------------------------------------------------- CSRF + session
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    app.jinja_env.globals["csrf_field"] = lambda: Markup(
        f'<input type="hidden" name="_csrf" value="{csrf_token()}">')
    app.jinja_env.globals.update(
        DOCUMENT_TYPES=DOCUMENT_TYPES, CIVIL_STATUSES=CIVIL_STATUSES, STATUSES=Status.ALL)

    @app.before_request
    def protect_and_load_user():
        if request.method == "POST":
            token = session.get("_csrf")
            if not token or token != request.form.get("_csrf"):
                abort(400)
        user_id = session.get("user_id")
        g.user = User.get(user_id) if user_id else None

    # --------------------------------------------------------------- decorators
    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not g.user.is_admin:
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def resident_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user.is_admin or g.user.resident_id is None:
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    # --------------------------------------------------------------------- auth
    @app.route("/")
    def home():
        if g.user is None:
            return redirect(url_for("login"))
        return redirect(url_for("admin_dashboard" if g.user.is_admin else "resident_dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = Auth.authenticate(request.form.get("username", ""), request.form.get("password", ""))
            if user:
                session.clear()
                session["user_id"] = user.id
                return redirect(url_for("home"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        form = request.form
        if request.method == "POST":
            try:
                resident = Resident.from_form(form)
                resident.validate()
                # check the account details first so no half-created resident is left behind
                Auth.check_new_password(form.get("password", ""))
                if len(form.get("username", "").strip()) < 3:
                    raise ValidationError("Username must be at least 3 characters.")
                if db.query("SELECT id FROM users WHERE username = %s",
                            (form["username"].strip(),), one=True):
                    raise ValidationError("That username is already taken.")
                resident_id = RecordManager.create(resident)
                Auth.create_account(form["username"], form["password"], User.ROLE_RESIDENT, resident_id)
                flash("Account created. You can log in now.", "ok")
                return redirect(url_for("login"))
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("register.html", form=form)

    # ------------------------------------------------------------------ resident
    @app.route("/resident")
    @resident_required
    def resident_dashboard():
        dash = Dashboard(RecordManager.get(g.user.resident_id))
        return render_template("resident_dashboard.html", dash=dash)

    @app.route("/resident/requests", methods=["POST"])
    @resident_required
    def resident_request():
        try:
            RequestManager.create(DocumentRequest(
                g.user.resident_id, request.form.get("document_type", ""), request.form.get("purpose", "")))
            flash("Request submitted.", "ok")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("resident_dashboard"))

    @app.route("/resident/appointments", methods=["POST"])
    @resident_required
    def resident_appointment():
        try:
            AppointmentManager.create(Appointment.from_form(g.user.resident_id, request.form))
            flash("Appointment booked.", "ok")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("resident_dashboard"))

    # ----------------------------------------------------------------- settings
    @app.route("/settings")
    @login_required
    def settings():
        resident = RecordManager.get(g.user.resident_id) if g.user.resident_id else None
        return render_template("settings.html", form=resident.as_form() if resident else None)

    @app.route("/settings/password", methods=["POST"])
    @login_required
    def settings_password():
        try:
            Auth.change_password(g.user.id, request.form.get("current_password", ""),
                                 request.form.get("new_password", ""), request.form.get("confirm_password", ""))
            flash("Password changed.", "ok")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("settings"))

    @app.route("/settings/profile", methods=["POST"])
    @resident_required
    def settings_profile():
        try:
            RecordManager.update(Resident.from_form(request.form, id=g.user.resident_id))
            flash("Profile updated.", "ok")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("settings"))

    # -------------------------------------------------------------------- admin
    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        return render_template("admin_dashboard.html", report=ReportGenerator.generate())

    @app.route("/admin/residents")
    @admin_required
    def admin_residents():
        return render_template("admin_residents.html", residents=RecordManager.all())

    @app.route("/admin/residents/new", methods=["GET", "POST"])
    @admin_required
    def admin_resident_new():
        form = request.form
        if request.method == "POST":
            try:
                resident = Resident.from_form(form)
                resident.validate()
                username, password = form.get("username", "").strip(), form.get("password", "")
                if username or password:  # optional login account for this resident
                    Auth.check_new_password(password)
                    if len(username) < 3:
                        raise ValidationError("Username must be at least 3 characters.")
                    if db.query("SELECT id FROM users WHERE username = %s", (username,), one=True):
                        raise ValidationError("That username is already taken.")
                resident_id = RecordManager.create(resident)
                if username:
                    Auth.create_account(username, password, User.ROLE_RESIDENT, resident_id)
                flash("Resident added.", "ok")
                return redirect(url_for("admin_residents"))
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("admin_resident_form.html", form=form, resident_id=None)

    @app.route("/admin/residents/<int:resident_id>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_resident_edit(resident_id):
        existing = RecordManager.get(resident_id)
        if existing is None:
            abort(404)
        form = existing.as_form()
        if request.method == "POST":
            form = request.form
            try:
                RecordManager.update(Resident.from_form(form, id=resident_id))
                flash("Resident updated.", "ok")
                return redirect(url_for("admin_residents"))
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("admin_resident_form.html", form=form, resident_id=resident_id)

    @app.route("/admin/residents/<int:resident_id>/delete", methods=["POST"])
    @admin_required
    def admin_resident_delete(resident_id):
        RecordManager.delete(resident_id)
        flash("Resident deleted.", "ok")
        return redirect(url_for("admin_residents"))

    @app.route("/admin/residents/<int:resident_id>/reset-password", methods=["POST"])
    @admin_required
    def admin_reset_password(resident_id):
        try:
            Auth.reset_resident_password(resident_id, request.form.get("new_password", ""))
            flash("Password reset.", "ok")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("admin_residents"))

    @app.route("/admin/requests")
    @admin_required
    def admin_requests():
        return render_template("admin_requests.html", requests=RequestManager.all())

    @app.route("/admin/requests/<int:request_id>/status", methods=["POST"])
    @admin_required
    def admin_request_status(request_id):
        try:
            RequestManager.set_status(request_id, request.form.get("status", ""), request.form.get("remarks"))
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("admin_requests"))

    @app.route("/admin/appointments")
    @admin_required
    def admin_appointments():
        return render_template("admin_appointments.html", appointments=AppointmentManager.all())

    @app.route("/admin/appointments/<int:appointment_id>/status", methods=["POST"])
    @admin_required
    def admin_appointment_status(appointment_id):
        try:
            AppointmentManager.set_status(appointment_id, request.form.get("status", ""))
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("admin_appointments"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
