# Barangay Service Management System (Python / Flask / MySQL)

Residents register, request barangay documents, book appointments, track status and manage their
profile and password. Barangay staff (admin) manage residents, process requests and appointments,
reset resident passwords and view reports.

Stack: Python, Flask, MySQL, mysql-connector-python (as in the project proposal).

## Files
- `app.py`     routes (login, resident, settings, admin) + CSRF protection
- `models.py`  OOP classes: User, Admin, Auth, Resident, RecordManager, Request, DocumentRequest,
               RequestManager, Appointment, AppointmentManager, Dashboard, Report, ReportGenerator, Status
- `db.py`      MySQL connection and automatic table creation
- `templates/` HTML pages, `static/style.css`

## Run on your computer
1. Install Python 3.10+ from python.org (tick "Add Python to PATH") and MySQL.
2. Open this folder in VS Code, then in the terminal:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `DB_PASSWORD` (your MySQL root password) and `SECRET_KEY`.
   If a value contains spaces or `#`, put it in quotes.
4. `python app.py`, then open http://127.0.0.1:5000
5. Log in as `admin` / `admin123` (change it in Settings). Tables are created automatically.

## Put it online (free): Aiven (MySQL) + Render (website)
Free plans change, so check each site's current limits.

### 1. Database on Aiven
1. Sign up at aiven.io, create a service, choose **MySQL** and the **Free** plan, and wait until it is running.
2. Copy the connection details: Host, Port, User, Password and Database name (usually `defaultdb`).
3. If the website later cannot connect, download Aiven's CA certificate, add it to this folder as `ca.pem`
   and set the variable `DB_SSL_CA=ca.pem`.

### 2. Code on GitHub
1. Create a free GitHub account and a new repository.
2. Upload all files in this folder. **Do not upload your `.env` file** (it contains passwords).

### 3. Website on Render
1. Sign up at render.com with GitHub, then **New > Web Service** and pick your repository.
2. Settings: Runtime **Python 3**, Build command `pip install -r requirements.txt`,
   Start command `gunicorn app:app`, Instance type **Free**.
3. Add these Environment Variables:
   `SECRET_KEY` (long random text), `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
   (from Aiven), `ADMIN_USERNAME`, `ADMIN_PASSWORD` (choose a strong one), `COOKIE_SECURE=1`,
   and `PYTHON_VERSION=3.12.3`.
4. Click **Create Web Service**. When the deploy finishes, open the `https://....onrender.com` address
   shown at the top. Log in with your ADMIN_USERNAME / ADMIN_PASSWORD.

Notes: a free Render site goes to sleep when nobody visits for a while, so the first page after a pause
can take about a minute to load. Anyone with the link can open the site; do not enter real residents'
personal data in a demo.
