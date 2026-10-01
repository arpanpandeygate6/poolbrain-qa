import datetime as dt
import uuid

import pytest

from utils.naming import qa_auto_name

JOB_TYPE = "Weekly Service"


@pytest.mark.regression
@pytest.mark.db
@pytest.mark.flow("job-creation")
def test_api_job_is_saved_with_entered_details(logged_in_api, db):
    customers = logged_in_api.customers().json()["customers"]
    assert customers, "The testing company has no customers; check the seeded test data"
    customer = customers[0]
    name = qa_auto_name(f"job-{uuid.uuid4().hex[:6]}")
    scheduled_date = (dt.datetime.now(dt.UTC).date() + dt.timedelta(days=7)).isoformat()

    response = logged_in_api.create_job(name, customer["id"], JOB_TYPE, scheduled_date)

    assert response.status_code == 201, f"Create job returned {response.status_code}: {response.text[:200]}"
    job = response.json()["job"]
    assert job["name"] == name

    # JOB-1: saved with the entered details. JOB-2: a new job starts as Scheduled.
    saved = db.wait_for_row(
        "SELECT name, customer_id, job_type, DATE_FORMAT(scheduled_date, '%%Y-%%m-%%d') AS scheduled_date, status"
        " FROM jobs WHERE id = %s",
        (job["id"],),
        purpose=f"job {job['id']} saved",
    )
    assert saved == {
        "name": name,
        "customer_id": customer["id"],
        "job_type": JOB_TYPE,
        "scheduled_date": scheduled_date,
        "status": "Scheduled",
    }, "The saved job does not match what was entered"
