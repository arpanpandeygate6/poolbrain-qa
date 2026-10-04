# Postman release checks → pytest smoke tests

Story 3.1: every request in the Postman release-gate collection is replaced by one read-only pytest test marked `smoke`. Fill in one row per request when porting; **no request may be left unmapped** before Postman is retired (Story 3.3).

How to port a request:
- Make the same call through `ApiClient` (add a small method to `utils/api_client.py` if needed). On Preprod, PROD and NPP it refuses anything but reads and the login, before any network call.
- Assert the same things the Postman tests assert (status, key fields, values), with plain failure messages.
- Mark it `@pytest.mark.smoke` and `@pytest.mark.flow("<id>")` with a flow from `flows/inventory.yaml`. Where none fits, the QA lead adds one in the same PR.
- Check the data belongs to the testing company with `assert_testing_company(...)` (`utils/testing_company.py`).
- Put it in `tests/test_smoke.py`, or a `tests/test_smoke_<area>.py` file for a large area.

| Postman folder / request | Method and path | pytest test (`test_id`) | Notes |
|---|---|---|---|
| (not ported yet: the collection hasn't been received) | | | |

Already in place, not from Postman: `api:tests/test_smoke.py::test_smoke_customers_are_listed` (the customer list answers and holds only the testing company's customers).
