"""Smoke tests read only the testing company's data (Story 3.1, SEC-06)."""

from config import Settings

# Where a record names its company. Check these against the real API before
# the first port from Postman.
COMPANY_FIELDS = ("company_id", "companyId", "company")


def assert_testing_company(records: list[dict] | dict, settings: Settings) -> None:
    """Fail unless every record belongs to the testing company.

    On Preprod, PROD and NPP, TESTING_COMPANY_ID must be set. On UAT and the
    pretend PoolBrain the check is skipped when it isn't.
    """
    expected = settings.testing_company_id
    if not expected:
        assert not settings.read_only, f"TESTING_COMPANY_ID is not set for {settings.env}: smoke tests can't check whose data they read"
        return
    for record in records if isinstance(records, list) else [records]:
        field = next((f for f in COMPANY_FIELDS if f in record), None)
        assert field, f"The record has no company field ({', '.join(COMPANY_FIELDS)}): {sorted(record)[:10]}"
        value = record[field]["id"] if isinstance(record[field], dict) else record[field]
        assert str(value) == expected, f"A record belongs to company {value}, not the testing company {expected}"
