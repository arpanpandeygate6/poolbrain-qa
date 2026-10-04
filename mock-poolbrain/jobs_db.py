"""Database for the pretend PoolBrain: a MySQL database standing in for UAT's.

The app writes as the MySQL root user. Tests read through a separate
SELECT-only user (DB_USER / DB_PASSWORD, the same variables `ReadReplica`
uses), as they will on UAT's read replica. The database is seeded with the
testing company's baseline customers.

Settings (environment variables):
  DB_HOST, DB_PORT, DB_NAME     where MySQL runs (default 127.0.0.1:3307, poolbrain)
  MOCK_DB_ROOT_PASSWORD         the MySQL root password, for the app's writes
  DB_USER, DB_PASSWORD          the read-only user created for the tests
"""

import os
import re
import time
from datetime import date

import pymysql
import pymysql.cursors

JOB_TYPES = ("Weekly Service", "Repair", "Green Pool Cleanup", "Equipment Install")
SEEDED_CUSTOMERS = ("QA Testing Co - Customer A", "QA Testing Co - Customer B")
NEW_JOB_STATUS = "Scheduled"

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS customers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(200) NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        customer_id INT NOT NULL,
        job_type VARCHAR(50) NOT NULL,
        scheduled_date DATE NOT NULL,
        status VARCHAR(30) NOT NULL,
        created_by VARCHAR(200) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    )""",
)


class ValidationError(ValueError):
    """A job request that breaks a business rule; the message is shown to the user."""


def _connect(database: str | None = None):
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3307")),
        user="root",
        password=os.environ["MOCK_DB_ROOT_PASSWORD"],
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def db_name() -> str:
    name = os.getenv("DB_NAME", "poolbrain")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit(f"DB_NAME '{name}' may only contain letters, digits and underscores")
    return name


def setup(timeout: float = 90) -> None:
    """Wait for MySQL, create the schema and seed data, and (re)create the read-only test user."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            conn = _connect()
            break
        except pymysql.err.OperationalError:
            if time.monotonic() > deadline:
                raise SystemExit("MySQL did not become ready; is the database container running?")
            time.sleep(2)

    name = db_name()
    with conn, conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}`")
        cur.execute(f"USE `{name}`")
        for statement in SCHEMA:
            cur.execute(statement)
        for customer in SEEDED_CUSTOMERS:
            cur.execute("INSERT IGNORE INTO customers (name) VALUES (%s)", (customer,))

        user, password = os.getenv("DB_USER", ""), os.getenv("DB_PASSWORD", "")
        if user and password:
            cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (user, password))
            cur.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (user, password))
            cur.execute(f"GRANT SELECT ON `{name}`.* TO %s@'%%'", (user,))


def customers() -> list[dict]:
    with _connect(db_name()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM customers ORDER BY name")
        return list(cur.fetchall())


def _job_row(cur, job_id: int) -> dict | None:
    cur.execute(
        """SELECT j.id, j.name, j.customer_id, c.name AS customer_name, j.job_type,
                  DATE_FORMAT(j.scheduled_date, '%%Y-%%m-%%d') AS scheduled_date, j.status, j.created_by
           FROM jobs j JOIN customers c ON c.id = j.customer_id WHERE j.id = %s""",
        (job_id,),
    )
    return cur.fetchone()


def jobs(limit: int = 50) -> list[dict]:
    with _connect(db_name()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT %s", (limit,))
        return [_job_row(cur, row["id"]) for row in cur.fetchall()]


def get_job(job_id: int) -> dict | None:
    with _connect(db_name()) as conn, conn.cursor() as cur:
        return _job_row(cur, job_id)


def create_job(name, customer_id, job_type, scheduled_date, created_by: str) -> dict:
    """Validate and save a new job. Business rules: every field is required, the customer
    must exist, the job type must be a known one, and a new job starts as 'Scheduled'."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("Job name is required.")
    if len(name) > 200:
        raise ValidationError("Job name must be 200 characters or fewer.")
    if job_type not in JOB_TYPES:
        raise ValidationError(f"Job type must be one of: {', '.join(JOB_TYPES)}.")
    try:
        day = date.fromisoformat(str(scheduled_date or ""))
    except ValueError:
        raise ValidationError("Scheduled date must be a date like 2026-10-15.")
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        raise ValidationError("Please choose a customer.")

    with _connect(db_name()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM customers WHERE id = %s", (customer_id,))
        if not cur.fetchone():
            raise ValidationError("Customer not found.")
        cur.execute(
            "INSERT INTO jobs (name, customer_id, job_type, scheduled_date, status, created_by)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (name, customer_id, job_type, day, NEW_JOB_STATUS, created_by),
        )
        return _job_row(cur, cur.lastrowid)
