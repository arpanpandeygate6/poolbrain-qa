"""Read-only release checks (Story 3.1). They run on every environment through the
`smoke` workflow (Story 3.2), so they only read, and only the testing company's data.

The Postman release-gate requests are ported here one by one; postman-mapping.md
lists each request and the test that replaces it. The first check below runs today
on UAT and the pretend PoolBrain.
"""

import pytest

from utils.testing_company import assert_testing_company


@pytest.mark.smoke
@pytest.mark.flow("job-creation")
def test_smoke_customers_are_listed(logged_in_api, settings):
    """The customer list answers, has customers, and holds only the testing company's."""
    response = logged_in_api.customers()

    assert response.status_code == 200, f"Customer list returned {response.status_code}: {response.text[:200]}"
    customers = response.json()["customers"]
    assert customers, "The customer list is empty; the testing company should have its baseline customers"
    assert all({"id", "name"} <= set(c) for c in customers), "Every customer should have an id and a name"
    assert_testing_company(customers, settings)
