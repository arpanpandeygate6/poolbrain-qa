"""Environment configuration for the API tests.

Pick the target with POOLBRAIN_ENV (uat, preprod, prod, npp).

Locally, only UAT is allowed; its values are read from api-tests/.env.uat.
Preprod, PROD and NPP credentials exist only as CI secrets (PRD FR-03), so
those environments run only in CI, where values come from environment
variables and no .env file is read. Never commit real credentials.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENVIRONMENTS = ("uat", "preprod", "prod", "npp")

# Only smoke tests may run here: no writes, testing company only.
READ_ONLY_ENVIRONMENTS = ("preprod", "prod", "npp")


@dataclass(frozen=True)
class Settings:
    env: str
    api_base_url: str
    api_token: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    @property
    def read_only(self) -> bool:
        return self.env in READ_ONLY_ENVIRONMENTS


def load_settings(env: str | None = None) -> Settings:
    env = (env or os.getenv("POOLBRAIN_ENV", "uat")).lower()
    if env not in ENVIRONMENTS:
        raise ValueError(f"Unknown POOLBRAIN_ENV '{env}'. Use one of: {', '.join(ENVIRONMENTS)}")

    in_ci = os.getenv("CI", "").lower() == "true"
    if env in READ_ONLY_ENVIRONMENTS and not in_ci:
        raise RuntimeError(
            f"'{env}' runs only in CI: its credentials are CI secrets and must never be on a laptop."
        )
    if not in_ci:
        load_dotenv(Path(__file__).parent / ".env.uat")

    return Settings(
        env=env,
        api_base_url=os.getenv("API_BASE_URL", ""),
        api_token=os.getenv("API_TOKEN", ""),
        db_host=os.getenv("DB_HOST", ""),
        db_port=int(os.getenv("DB_PORT", "3306")),
        db_name=os.getenv("DB_NAME", ""),
        db_user=os.getenv("DB_USER", ""),
        db_password=os.getenv("DB_PASSWORD", ""),
    )
