import pytest


@pytest.mark.regression
@pytest.mark.flow("login")
def test_api_user_can_log_in(api, settings):
    if not (settings.api_user_email and settings.api_user_password):
        pytest.skip(f"API_USER_EMAIL and API_USER_PASSWORD are not set for {settings.env}")

    response = api.login(settings.api_user_email, settings.api_user_password)

    assert response.status_code == 200, f"Login returned {response.status_code}: {response.text[:200]}"
    body = response.json()
    assert body.get("token"), "Login response has no token"
    assert body["user"]["email"].lower() == settings.api_user_email.lower(), (
        f"Logged in as {body['user']['email']}, expected {settings.api_user_email}"
    )
