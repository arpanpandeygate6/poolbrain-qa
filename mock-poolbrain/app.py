"""Pretend PoolBrain: a stand-in for the real UAT site while we have no UAT access.

It has a login page, a job list and a new-job form, and matching API
endpoints, backed by a MySQL database (see jobs_db.py), so the test setup can
be built and run end to end. It is not PoolBrain: the API paths, fields and
screens are our best guess and get corrected when the tests point at real UAT.

Accounts come from the same variables the tests use, so nothing is hardcoded:
  OFFICE_ADMIN_EMAIL / OFFICE_ADMIN_PASSWORD   browser login (ui-tests)
  API_USER_EMAIL / API_USER_PASSWORD           API login (api-tests)
Locally they are read from ui-tests/.env.uat, api-tests/.env.uat and
mock-poolbrain/.env; in CI (CI=true) only from environment variables.

Run from the repo root (starts MySQL in Docker first):
    mock-poolbrain/start.sh
Then open http://127.0.0.1:5050/login
"""

import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string, request

import jobs_db

REPO = Path(__file__).resolve().parent.parent
PORT = int(os.getenv("MOCK_PORT", "5050"))
SESSION_COOKIE = "pb_session"

ROLES = {
    "OFFICE_ADMIN": ("office_admin", "Office", "Admin"),
    "API_USER": ("api_user", "API", "Tester"),
}


def load_accounts() -> dict[str, dict]:
    if os.getenv("CI", "").lower() != "true":
        load_dotenv(REPO / "api-tests" / ".env.uat")
        load_dotenv(REPO / "ui-tests" / ".env.uat")
        load_dotenv(REPO / "mock-poolbrain" / ".env")
    accounts = {}
    for prefix, (role, first_name, last_name) in ROLES.items():
        email, password = os.getenv(f"{prefix}_EMAIL", ""), os.getenv(f"{prefix}_PASSWORD", "")
        if email and password:
            accounts[email.lower()] = {
                "password": password,
                "user": {"email": email, "first_name": first_name, "last_name": last_name, "role": role},
            }
    return accounts


app = Flask(__name__)
ACCOUNTS: dict[str, dict] = {}
SESSIONS: dict[str, str] = {}  # token -> email


def authenticate(email: str, password: str) -> str | None:
    """Return a new session token, or None when the email or password is wrong."""
    account = ACCOUNTS.get(email.strip().lower())
    if not account or not secrets.compare_digest(account["password"], password):
        return None
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = email.strip().lower()
    return token


def user_for(token: str | None) -> dict | None:
    email = SESSIONS.get(token or "")
    return ACCOUNTS[email]["user"] if email else None


def browser_user() -> dict | None:
    return user_for(request.cookies.get(SESSION_COOKIE))


def api_user() -> dict | None:
    header = request.headers.get("Authorization", "")
    return user_for(header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else None)


# ---- Browser pages -------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} | Pool Brain (pretend)</title>
<style>
  :root { --blue: #4fade3; --ink: #1d1d1f; --muted: #9a9a9a; --line: #e3e3e3; --bg: #e9ecef; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: var(--bg); color: var(--ink);
         font-family: "Source Sans Pro", "Segoe UI", Helvetica, Arial, sans-serif; }
  .banner { background: #fff3cd; color: #664d03; text-align: center; padding: 6px; font-size: 13px; }
  .card { width: min(420px, calc(100% - 32px)); margin: 48px auto; background: #fff; padding: 24px 28px 28px;
          box-shadow: 0 2px 12px rgba(0,0,0,.12); }
  .logo { text-align: center; font-size: 30px; font-weight: 700; margin: 0; }
  .logo .pool { color: var(--blue); }
  h1 { text-align: center; font-size: 22px; font-weight: 800; text-transform: uppercase; letter-spacing: .5px; }
  .field { position: relative; margin: 0 0 18px; }
  input[type=email], input[type=password], input[type=text] {
    width: 100%; padding: 14px 44px 14px 16px; font-size: 17px; border: 1px solid var(--line);
    box-shadow: 0 2px 4px rgba(0,0,0,.08); }
  input::placeholder { color: var(--muted); }
  .eye { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); background: none; border: 0;
         color: var(--blue); cursor: pointer; font-size: 13px; }
  .submit { width: 100%; padding: 14px; border: 0; background: var(--blue); color: #fff; font-size: 19px;
            text-transform: uppercase; letter-spacing: .5px; cursor: pointer; margin-top: 8px; }
  .error { background: #fdecea; color: #b3261e; padding: 10px 12px; margin-bottom: 16px; font-size: 15px; }
  .muted { text-align: center; margin-top: 18px; font-size: 16px; }
  a { color: var(--blue); text-decoration: none; }
  .topbar { display: flex; justify-content: space-between; align-items: center; background: #fff; padding: 12px 24px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .topbar .logo { font-size: 24px; }
  .wide { width: min(960px, calc(100% - 32px)); }
  select, input[type=date] { width: 100%; padding: 13px 16px; font-size: 17px; border: 1px solid var(--line);
    background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,.08); }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); }
  th { font-size: 13px; text-transform: uppercase; color: #555; }
  .actions { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .button { display: inline-block; padding: 10px 18px; background: var(--blue); color: #fff;
            text-transform: uppercase; letter-spacing: .5px; }
  .success { background: #e7f6ec; color: #1e6b3a; padding: 10px 12px; margin-bottom: 16px; }
</style>
</head>
<body>
<div class="banner">Pretend PoolBrain for test development. Not the real site.</div>
{{ body | safe }}
<script>
  document.querySelectorAll('.eye').forEach(function (button) {
    button.addEventListener('click', function () {
      var input = button.previousElementSibling;
      input.type = input.type === 'password' ? 'text' : 'password';
      button.setAttribute('aria-label', input.type === 'password' ? 'Show password' : 'Hide password');
    });
  });
</script>
</body>
</html>"""

LOGIN_BODY = """
<main class="card">
  <p class="logo"><span class="pool">pool</span>brain</p>
  <h1>Sign in</h1>
  {% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
  <form method="post" action="/login">
    <div class="field">
      <input type="email" name="email" placeholder="Enter your email" value="{{ email }}" autocomplete="username">
    </div>
    <div class="field">
      <input type="password" name="password" placeholder="Enter your password" autocomplete="current-password">
      <button type="button" class="eye" aria-label="Show password">show</button>
    </div>
    <button type="submit" class="submit">Sign in</button>
  </form>
  <p class="muted">Don't have an account? <a href="#">Sign Up</a></p>
</main>
"""

TOPBAR = """
<header class="topbar">
  <p class="logo"><a href="/dashboard"><span class="pool">pool</span><span style="color:#1d1d1f">brain</span></a></p>
  <nav><a href="/jobs">Jobs</a></nav>
  <span data-testid="signed-in-user">{{ user.first_name }} {{ user.last_name }} ({{ user.email }})</span>
</header>
"""

JOBS_BODY = TOPBAR + """
<main class="card wide">
  <h1>Jobs</h1>
  {% if created %}<div class="success" role="status">Job "{{ created.name }}" created.</div>{% endif %}
  <div class="actions"><span>{{ jobs | length }} most recent jobs</span><a class="button" href="/jobs/new">New job</a></div>
  <table>
    <thead><tr><th>Job</th><th>Customer</th><th>Type</th><th>Scheduled</th><th>Status</th></tr></thead>
    <tbody>
    {% for job in jobs %}
      <tr><td>{{ job.name }}</td><td>{{ job.customer_name }}</td><td>{{ job.job_type }}</td>
          <td>{{ job.scheduled_date }}</td><td>{{ job.status }}</td></tr>
    {% else %}
      <tr><td colspan="5">No jobs yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</main>
"""

NEW_JOB_BODY = TOPBAR + """
<main class="card">
  <h1>New job</h1>
  {% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
  <form method="post" action="/jobs/new">
    <div class="field"><input type="text" name="name" placeholder="Enter job name" value="{{ form.name }}"></div>
    <div class="field">
      <select name="customer_id" aria-label="Customer">
        <option value="">Select a customer</option>
        {% for c in customers %}
          <option value="{{ c.id }}" {% if form.customer_id == c.id|string %}selected{% endif %}>{{ c.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="field">
      <select name="job_type" aria-label="Job type">
        <option value="">Select a job type</option>
        {% for t in job_types %}<option {% if form.job_type == t %}selected{% endif %}>{{ t }}</option>{% endfor %}
      </select>
    </div>
    <div class="field">
      <input type="date" name="scheduled_date" aria-label="Scheduled date" value="{{ form.scheduled_date }}">
    </div>
    <button type="submit" class="submit">Create job</button>
  </form>
</main>
"""

DASHBOARD_BODY = """
<header class="topbar">
  <p class="logo"><span class="pool">pool</span>brain</p>
  <span data-testid="signed-in-user">{{ user.first_name }} {{ user.last_name }} ({{ user.email }})</span>
</header>
<main class="card">
  <h1>Dashboard</h1>
  <p class="muted">You are signed in as {{ user.role }}.</p>
  <p class="muted"><a href="/jobs">Jobs</a></p>
  <form method="post" action="/logout"><button type="submit" class="submit">Sign out</button></form>
</main>
"""


def page(title: str, body: str, status: int = 200, **context):
    return render_template_string(PAGE, title=title, body=render_template_string(body, **context)), status


@app.get("/")
def home():
    return redirect("/login")


@app.get("/login")
def login_page():
    return page("Sign in", LOGIN_BODY, email="", error="")


@app.post("/login")
def login_submit():
    email, password = request.form.get("email", ""), request.form.get("password", "")
    token = authenticate(email, password) if email and password else None
    if not token:
        error = "Please enter your email and password." if not (email and password) else "Invalid email or password."
        return page("Sign in", LOGIN_BODY, status=401, email=email, error=error)
    response = redirect("/dashboard")
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax")
    return response


@app.get("/dashboard")
def dashboard():
    user = user_for(request.cookies.get(SESSION_COOKIE))
    if not user:
        return redirect("/login")
    return page("Dashboard", DASHBOARD_BODY, user=user)


@app.get("/jobs")
def jobs_page():
    user = browser_user()
    if not user:
        return redirect("/login")
    created = jobs_db.get_job(int(request.args["created"])) if request.args.get("created", "").isdigit() else None
    return page("Jobs", JOBS_BODY, user=user, jobs=jobs_db.jobs(), created=created)


@app.get("/jobs/new")
def new_job_page():
    user = browser_user()
    if not user:
        return redirect("/login")
    return page("New job", NEW_JOB_BODY, user=user, customers=jobs_db.customers(), job_types=jobs_db.JOB_TYPES,
                form={}, error="")


@app.post("/jobs/new")
def new_job_submit():
    user = browser_user()
    if not user:
        return redirect("/login")
    form = request.form.to_dict()
    try:
        job = jobs_db.create_job(form.get("name"), form.get("customer_id"), form.get("job_type"),
                                 form.get("scheduled_date"), created_by=user["email"])
    except jobs_db.ValidationError as e:
        return page("New job", NEW_JOB_BODY, status=400, user=user, customers=jobs_db.customers(),
                    job_types=jobs_db.JOB_TYPES, form=form, error=str(e))
    return redirect(f"/jobs?created={job['id']}")


@app.post("/logout")
def logout():
    SESSIONS.pop(request.cookies.get(SESSION_COOKIE, ""), None)
    response = redirect("/login")
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---- API -----------------------------------------------------------------


@app.get("/api/health")
def health():
    return jsonify(status="ok")


@app.post("/api/auth/login")
def api_login():
    body = request.get_json(silent=True) or {}
    email, password = body.get("email", ""), body.get("password", "")
    if not email or not password:
        return jsonify(error="email and password are required"), 400
    token = authenticate(email, password)
    if not token:
        return jsonify(error="Invalid email or password"), 401
    return jsonify(token=token, user=user_for(token))


@app.get("/api/me")
def api_me():
    user = api_user()
    if not user:
        return jsonify(error="Not signed in"), 401
    return jsonify(user=user)


@app.get("/api/customers")
def api_customers():
    if not api_user():
        return jsonify(error="Not signed in"), 401
    return jsonify(customers=jobs_db.customers())


@app.post("/api/jobs")
def api_create_job():
    user = api_user()
    if not user:
        return jsonify(error="Not signed in"), 401
    body = request.get_json(silent=True) or {}
    try:
        job = jobs_db.create_job(body.get("name"), body.get("customer_id"), body.get("job_type"),
                                 body.get("scheduled_date"), created_by=user["email"])
    except jobs_db.ValidationError as e:
        return jsonify(error=str(e)), 400
    return jsonify(job=job), 201


@app.get("/api/jobs/<int:job_id>")
def api_get_job(job_id: int):
    if not api_user():
        return jsonify(error="Not signed in"), 401
    job = jobs_db.get_job(job_id)
    return (jsonify(job=job), 200) if job else (jsonify(error="Job not found"), 404)


if __name__ == "__main__":
    ACCOUNTS.update(load_accounts())
    if not ACCOUNTS:
        sys.exit(
            "No accounts: set OFFICE_ADMIN_EMAIL/OFFICE_ADMIN_PASSWORD and/or API_USER_EMAIL/API_USER_PASSWORD "
            "(in ui-tests/.env.uat and api-tests/.env.uat, or as environment variables)."
        )
    jobs_db.setup()
    print(f"Pretend PoolBrain on http://127.0.0.1:{PORT}/login with {len(ACCOUNTS)} account(s)")
    app.run(host="127.0.0.1", port=PORT)
