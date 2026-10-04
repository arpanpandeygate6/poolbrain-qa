"""Unit tests for the smoke safeguards (Story 3.1). No network: nothing may be sent."""

import pytest

import config
from config import Settings
from utils.api_client import LOGIN_PATH, ApiClient, ReadOnlyError
from utils.testing_company import assert_testing_company


class NoNetwork:
    """A session that fails the test if anything would be sent."""

    def __init__(self):
        self.headers = {}

    def request(self, method, url, **kwargs):
        raise AssertionError(f"{method} {url} would have been sent")


def client(read_only, env="prod"):
    c = ApiClient("https://api.example", read_only=read_only, env=env)
    c.session = NoNetwork()
    return c


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
def test_read_only_refuses_writes_before_any_network_call(method):
    with pytest.raises(ReadOnlyError, match=rf"{method.upper()} jobs refused: prod is read-only.*Nothing was sent"):
        client(read_only=True).request(method, "jobs")


def test_read_only_allows_reads_and_the_login():
    c = client(read_only=True)
    for method, path in (("GET", "customers"), ("HEAD", "customers"), ("POST", LOGIN_PATH), ("POST", f"/{LOGIN_PATH}")):
        with pytest.raises(AssertionError, match="would have been sent"):  # passed the guard
            c.request(method, path)


def test_create_job_is_refused_on_read_only():
    with pytest.raises(ReadOnlyError):
        client(read_only=True).create_job("x", 1, "Repair", "2026-10-10")


def test_uat_client_is_not_read_only():
    with pytest.raises(AssertionError, match="would have been sent"):
        client(read_only=False, env="uat").request("POST", "jobs")


def settings(**values):
    base = {"env": "uat", "api_base_url": "", "api_token": "", "api_user_email": "", "api_user_password": "",
            "db_host": "", "db_port": 3306, "db_name": "", "db_user": "", "db_password": ""}
    return Settings(**{**base, **values})


@pytest.mark.parametrize(
    "values, mode",
    [({"api_token": "k"}, "api-key"), ({"api_token": "k", "api_user_email": "a", "api_user_password": "b"}, "api-key"),
     ({"api_user_email": "a", "api_user_password": "b"}, "login"), ({"api_user_email": "a"}, "none"), ({}, "none")],
)
def test_auth_mode_is_chosen_by_which_variables_are_set(values, mode):
    assert settings(**values).auth_mode == mode


def test_read_only_environments_only_in_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(RuntimeError, match="'prod' runs only in CI"):
        config.load_settings("prod")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("TESTING_COMPANY_ID", "42")
    loaded = config.load_settings("prod")
    assert loaded.read_only and loaded.testing_company_id == "42"


def test_testing_company_check():
    prod = settings(env="prod", testing_company_id="42")
    assert_testing_company([{"id": 1, "company_id": 42}, {"id": 2, "companyId": "42"}, {"id": 3, "company": {"id": 42}}], prod)
    with pytest.raises(AssertionError, match="belongs to company 7, not the testing company 42"):
        assert_testing_company([{"company_id": 42}, {"company_id": 7}], prod)
    with pytest.raises(AssertionError, match="has no company field"):
        assert_testing_company({"id": 1}, prod)
    with pytest.raises(AssertionError, match="TESTING_COMPANY_ID is not set for prod"):
        assert_testing_company([{"id": 1}], settings(env="prod"))
    assert_testing_company([{"id": 1}], settings(env="uat"))  # UAT and the pretend site: skipped when unset
