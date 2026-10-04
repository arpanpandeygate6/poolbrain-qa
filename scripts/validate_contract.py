#!/usr/bin/env python3
"""Contract validator (AD-5): checks a handover file against its schema in contracts/.

Rules: `schema_version` must be the file's first field, its value must be one the
schema knows (anything else is rejected), and the file must match the schema.

CSV contracts (a schema with "x-csv-columns", for example audit-export) are checked
row by row instead: the header row must be exactly those columns in that order,
the file must use standard CSV quoting, and every row must match the schema.

Usage:
    python scripts/validate_contract.py failure-list path/to/failure-list.json
    python scripts/validate_contract.py --samples   # every contracts/samples/<name>*.json
Exit code 0 when valid, 1 otherwise. Producers call validate() before saving.
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


class ContractError(ValueError):
    """The file does not follow its contract; the message says why."""


def load_schema(name: str, contracts: Path = CONTRACTS) -> dict:
    path = contracts / f"{name}.schema.json"
    if not path.exists():
        raise ContractError(f"no contract named '{name}' (expected {path.name} in contracts/)")
    return json.loads(path.read_text(encoding="utf-8"))


def validate(name: str, data: dict, contracts: Path = CONTRACTS) -> None:
    """Raise ContractError when `data` doesn't follow contract `name`."""
    schema = load_schema(name, contracts)
    if not isinstance(data, dict) or not data:
        raise ContractError(f"{name}: the file must be a JSON object")
    if next(iter(data)) != "schema_version":
        raise ContractError(f"{name}: 'schema_version' must be the first field")
    known = schema["properties"]["schema_version"]["const"]
    if data["schema_version"] != known:
        raise ContractError(f"{name}: unknown schema_version {data['schema_version']!r} (this contract is version {known})")
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "(top level)"
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        raise ContractError(f"{name}: at {where}: {first.message}{more}")


def validate_csv(name: str, text: str, contracts: Path = CONTRACTS) -> None:
    """Raise ContractError when CSV `text` doesn't follow CSV contract `name`."""
    schema = load_schema(name, contracts)
    columns = schema.get("x-csv-columns")
    if not columns:
        raise ContractError(f"{name}: not a CSV contract")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as e:
        raise ContractError(f"{name}: not valid CSV: {e}")
    if not rows or rows[0] != columns:
        raise ContractError(f"{name}: the header row must be exactly: {','.join(columns)}")
    validator = Draft202012Validator(schema)
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(columns):
            raise ContractError(f"{name}: line {number} has {len(row)} fields, expected {len(columns)}")
        error = next(iter(sorted(validator.iter_errors(dict(zip(columns, row))), key=lambda e: list(e.path))), None)
        if error:
            where = "/".join(str(p) for p in error.absolute_path) or "(row)"
            raise ContractError(f"{name}: line {number}, {where}: {error.message}")


def validate_file(name: str, path: Path, contracts: Path = CONTRACTS) -> None:
    if path.suffix == ".csv":
        validate_csv(name, path.read_text(encoding="utf-8"), contracts)
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ContractError(f"{path}: not valid JSON: {e}")
    validate(name, data, contracts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate handover files against contracts/.")
    parser.add_argument("name", nargs="?", help="contract name, for example failure-list")
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument("--samples", action="store_true", help="validate every sample in contracts/samples/")
    parser.add_argument("--contracts", type=Path, default=CONTRACTS)
    args = parser.parse_args(argv)

    if args.samples:
        checks = []
        for schema in sorted(args.contracts.glob("*.schema.json")):
            name = schema.name.removesuffix(".schema.json")
            samples = sorted((args.contracts / "samples").glob(f"{name}*.json")) + sorted(
                (args.contracts / "samples").glob(f"{name}*.csv")
            )
            if not samples:
                print(f"FAILED: contract '{name}' has no sample in contracts/samples/")
                return 1
            checks += [(name, sample) for sample in samples]
    elif args.name and args.file:
        checks = [(args.name, args.file)]
    else:
        parser.error("give a contract name and a file, or --samples")

    failed = False
    for name, path in checks:
        try:
            validate_file(name, path, args.contracts)
            print(f"OK: {path.name} follows {name}")
        except ContractError as e:
            print(f"FAILED: {e}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
