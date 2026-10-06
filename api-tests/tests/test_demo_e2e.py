import pytest

# Throwaway tests for the end-to-end check. Never merge this branch.


@pytest.mark.regression
@pytest.mark.flow("job-creation")
@pytest.mark.parametrize("name", ["environment", "ignore", "bug"])
def test_demo_e2e_failure(name):
    assert False, f"Demo failure '{name}' for the end-to-end check (not a real defect)"
