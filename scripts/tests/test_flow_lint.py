"""Tests for the flow-tag linter. Each test builds a small repo in a temp folder
and runs the real pytest and Playwright collection against it."""

import json
import shutil
import textwrap
from pathlib import Path

import pytest

import flow_lint

REPO = Path(__file__).resolve().parents[2]
UI_NODE_MODULES = REPO / "ui-tests" / "node_modules"

INVENTORY = """\
qa_lead: Test Lead
flows:
  - id: login
    name: Login
    owner: someone
    layers: [api, ui]
    rules:
      - id: LOGIN-1
        tests: []
  - id: job-creation
    name: Job creation
    owner: someone
    layers: [api, db, ui]
    rules: []
"""

needs_playwright = pytest.mark.skipif(
    not (UI_NODE_MODULES / ".bin" / "playwright").exists(), reason="run `npm ci` in ui-tests first"
)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "flows").mkdir()
    (tmp_path / "flows" / "inventory.yaml").write_text(INVENTORY)
    api = tmp_path / "api-tests"
    (api / "tests").mkdir(parents=True)
    shutil.copy(REPO / "api-tests" / "pytest.ini", api / "pytest.ini")
    ui = tmp_path / "ui-tests"
    (ui / "tests").mkdir(parents=True)
    shutil.copy(REPO / "ui-tests" / "playwright.config.ts", ui / "playwright.config.ts")
    if UI_NODE_MODULES.exists():
        (ui / "node_modules").symlink_to(UI_NODE_MODULES)
    return tmp_path


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def run(repo: Path, capsys) -> tuple[int, str]:
    code = flow_lint.main(["--root", str(repo)])
    out = capsys.readouterr()
    return code, out.out + out.err


@needs_playwright
def test_empty_folders_pass(repo, capsys):
    code, out = run(repo, capsys)
    assert code == 0
    assert "0 tests found" in out


@needs_playwright
def test_tagged_tests_pass_and_are_counted_per_flow(repo, capsys):
    write(repo / "api-tests/tests/test_login.py", """
        import pytest

        @pytest.mark.flow("login")
        def test_api_login():
            pass

        @pytest.mark.flow("job-creation")
        @pytest.mark.parametrize("n", [1, 2])
        def test_create(n):
            pass
    """)
    write(repo / "api-tests/tests/test_module_mark.py", """
        import pytest

        pytestmark = pytest.mark.flow("login")

        class TestLogin:
            def test_in_class(self):
                pass
    """)
    write(repo / "ui-tests/tests/login.spec.ts", """
        import { test } from '@playwright/test';
        test.describe('Login', () => {
          test('office admin signs in', { tag: '@flow:login' }, async () => {});
        });
    """)
    code, out = run(repo, capsys)
    assert code == 0, out
    assert "  login           2   1      3" in out
    assert "  job-creation    1   0      1" in out
    assert "4 tests found" in out


@needs_playwright
def test_untagged_tests_fail_with_canonical_ids(repo, capsys):
    write(repo / "api-tests/tests/test_x.py", """
        class TestThing:
            def test_untagged(self):
                pass
    """)
    write(repo / "ui-tests/tests/sub/x.spec.ts", """
        import { test } from '@playwright/test';
        test.describe('Outer', () => {
          test.describe('Inner', () => {
            test('untagged', async () => {});
          });
        });
    """)
    code, out = run(repo, capsys)
    assert code == 1
    assert "api:tests/test_x.py::TestThing::test_untagged: no flow tag" in out
    assert "ui:tests/sub/x.spec.ts > Outer > Inner > untagged: no flow tag" in out


@needs_playwright
def test_unknown_flow_id_fails(repo, capsys):
    write(repo / "api-tests/tests/test_x.py", """
        import pytest

        @pytest.mark.flow("job-creaton")
        def test_typo():
            pass
    """)
    write(repo / "ui-tests/tests/x.spec.ts", """
        import { test } from '@playwright/test';
        test('typo', { tag: '@flow:logn' }, async () => {});
    """)
    code, out = run(repo, capsys)
    assert code == 1
    assert "api:tests/test_x.py::test_typo: unknown flow ID 'job-creaton'" in out
    assert "ui:tests/x.spec.ts > typo: unknown flow ID 'logn'" in out


@needs_playwright
def test_two_flows_or_bad_marker_fail(repo, capsys):
    write(repo / "api-tests/tests/test_x.py", """
        import pytest

        @pytest.mark.flow("login")
        @pytest.mark.flow("job-creation")
        def test_two():
            pass

        @pytest.mark.flow()
        def test_empty_marker():
            pass
    """)
    code, out = run(repo, capsys)
    assert code == 1
    assert "test_two: more than one flow tag" in out
    assert "test_empty_marker: flow marker must name exactly one flow ID" in out


@needs_playwright
def test_skip_and_fixme_are_listed_but_do_not_fail(repo, capsys):
    write(repo / "api-tests/tests/test_x.py", """
        import pytest

        @pytest.mark.flow("login")
        @pytest.mark.skip(reason="later")
        def test_skipped():
            pass

        @pytest.mark.flow("login")
        @pytest.mark.skipif(True, reason="later")
        def test_skipif():
            pass
    """)
    write(repo / "ui-tests/tests/x.spec.ts", """
        import { test } from '@playwright/test';
        test.skip('skipped', { tag: '@flow:login' }, async () => {});
        test.fixme('broken', { tag: '@flow:job-creation' }, async () => {});
    """)
    code, out = run(repo, capsys)
    assert code == 0, out
    assert "Not covered: skipped or fixme (4):" in out
    assert "api:tests/test_x.py::test_skipped  [flow: login; skipped]" in out
    assert "api:tests/test_x.py::test_skipif  [flow: login; skipped]" in out
    assert "ui:tests/x.spec.ts > skipped  [flow: login; skipped]" in out
    assert "ui:tests/x.spec.ts > broken  [flow: job-creation; fixme]" in out


@pytest.mark.parametrize(
    "inventory, message",
    [
        ("flows: [", "flows/inventory.yaml: invalid YAML"),
        (INVENTORY.replace("id: job-creation", "id: login"), "flows/inventory.yaml: duplicate flow ID 'login'"),
        (INVENTORY.replace("id: job-creation", "id: Job_Creation"), "'Job_Creation' is not kebab-case"),
        (INVENTORY.replace("qa_lead: Test Lead", "qa_lead:"), "'qa_lead' must name the QA lead"),
        (INVENTORY.replace("layers: [api, ui]", "layers: [web]"), "flow 'login' 'layers' must be"),
        (INVENTORY.replace("    owner: someone\n    layers: [api, ui]", "    layers: [api, ui]"), "flow 'login' needs a 'owner'"),
        (INVENTORY.replace("layers: [api, ui]", "layers: [api, ui]\n    ui_top10: yes please"), "flow 'login' 'ui_top10' must be true or false"),
    ],
)
def test_malformed_inventory_fails(repo, capsys, inventory, message):
    (repo / "flows" / "inventory.yaml").write_text(inventory)
    code, out = run(repo, capsys)
    assert code == 1
    assert message in out


def test_unregistered_marker_is_a_collection_failure(repo, capsys):
    write(repo / "api-tests/tests/test_x.py", """
        import pytest

        @pytest.mark.flw("login")
        def test_x():
            pass
    """)
    code, out = run(repo, capsys)
    assert code == 1
    assert "pytest could not collect the API tests" in out


def test_real_inventory_is_valid():
    assert flow_lint.load_inventory(REPO / "flows" / "inventory.yaml") == ["login", "job-creation"]


@needs_playwright
def test_json_output_lists_every_test(repo, capsys, tmp_path):
    write(repo / "api-tests/tests/test_x.py", """
        import pytest

        @pytest.mark.flow("login")
        @pytest.mark.skip(reason="later")
        def test_a():
            pass
    """)
    out = tmp_path / "tests.json"
    assert flow_lint.main(["--root", str(repo), "--json", str(out)]) == 0
    assert json.loads(out.read_text()) == [
        {"test_id": "api:tests/test_x.py::test_a", "suite": "api", "flows": ["login"], "status": "skipped"}
    ]
