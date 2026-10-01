import allure
import pytest

from config import Settings, load_settings
from utils.api_client import ApiClient
from utils.db import ReadReplica


def pytest_addoption(parser):
    parser.addoption("--env", default=None, help="Target environment: uat, preprod, prod, npp")


@pytest.fixture(scope="session")
def settings(pytestconfig) -> Settings:
    return load_settings(pytestconfig.getoption("--env"))


def pytest_collection_modifyitems(config, items):
    """Group the API tests in the Allure report; on read-only environments, skip everything that is not smoke."""
    for item in items:
        item.add_marker(allure.parent_suite("poolbrain-api-tests"))

    env_settings = load_settings(config.getoption("--env"))
    if not env_settings.read_only:
        return
    skip = pytest.mark.skip(reason=f"{env_settings.env} is read-only: only smoke tests run here")
    for item in items:
        if "smoke" not in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def api(settings) -> ApiClient:
    if not settings.api_base_url:
        pytest.skip(f"API_BASE_URL is not set for {settings.env}")
    client = ApiClient(settings.api_base_url, settings.api_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def db(settings) -> ReadReplica:
    if not settings.db_host:
        pytest.skip(f"DB_HOST is not set for {settings.env}")
    replica = ReadReplica(
        settings.db_host, settings.db_port, settings.db_name, settings.db_user, settings.db_password
    )
    yield replica
    replica.close()
