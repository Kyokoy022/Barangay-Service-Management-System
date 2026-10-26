"""Database layer: MySQL connection, small query helpers and first-run setup."""
import os

import mysql.connector
from flask import g

try:  # load a local .env file if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _config(with_database=True):
    cfg = dict(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    if with_database:
        cfg["database"] = os.environ.get("DB_NAME", "barangay_db")
    ca = os.environ.get("DB_SSL_CA")  # optional: path to a CA certificate (some hosts require it)
    if ca:
        cfg["ssl_ca"] = ca
    return cfg


def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(autocommit=True, **_config())
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, params=(), one=False):
    cur = get_db().cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=()):
    cur = get_db().cursor()
    cur.execute(sql, params)
    last_id = cur.lastrowid
    cur.close()
    return last_id


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS residents (
        id INT AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(150) NOT NULL,
        address VARCHAR(255) NOT NULL,
        birth_date DATE NULL,
        contact_number VARCHAR(40) NULL,
        civil_status VARCHAR(30) NULL
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(60) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL,
        resident_id INT NULL,
        FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS document_requests (
        id INT AUTO_INCREMENT PRIMARY KEY,
        resident_id INT NOT NULL,
        document_type VARCHAR(80) NOT NULL,
        purpose VARCHAR(255) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        remarks VARCHAR(255) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS appointments (
        id INT AUTO_INCREMENT PRIMARY KEY,
        resident_id INT NOT NULL,
        purpose VARCHAR(255) NOT NULL,
        scheduled_at DATETIME NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
    )""",
]


def init_db(admin_hasher):
    """Create the database/tables if missing and add the first admin account."""
    name = os.environ.get("DB_NAME", "barangay_db")
    try:
        conn = mysql.connector.connect(autocommit=True, **_config())
    except mysql.connector.Error as err:
        if err.errno != 1049:  # 1049 = unknown database
            raise
        root = mysql.connector.connect(autocommit=True, **_config(with_database=False))
        root.cursor().execute(f"CREATE DATABASE IF NOT EXISTS `{name}`")
        root.close()
        conn = mysql.connector.connect(autocommit=True, **_config())
    cur = conn.cursor()
    for statement in SCHEMA:
        cur.execute(statement)
    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'ADMIN'")
    if cur.fetchone()[0] == 0:
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "admin123")
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'ADMIN')",
            (username, admin_hasher(password)),
        )
    cur.close()
    conn.close()
