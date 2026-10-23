"""Strict table intake using only the standard library, before any report write."""

import csv
from dataclasses import asdict, fields
from pathlib import Path
import re

from .core import Decision, FeatureSpec, Observation, validate
from .rolling import RollingSpec, validate_rolling


_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def _number(value, name, *, nullable=False):
    if nullable and value == "":
        return None
    if not _NUMBER.fullmatch(value):
        raise ValueError(f"{name} must be a decimal number" + (" or an empty cell" if nullable else ""))
    if re.fullmatch(r"[+-]?[0-9]+", value):
        # Retain exact integer source values in inputs.json, including values
        # above 2**53. Only the feature engine converts them to binary64.
        digits = value.lstrip("+-").lstrip("0") or "0"
        if len(digits) > 309:
            raise ValueError(f"{name} must be within the finite binary64 range")
        return int(("-" if value.startswith("-") else "") + digits)
    return float(value)


def _convert(record, cls):
    if cls is Observation:
        revision = record["revision"]
        if not re.fullmatch(r"[0-9]+", revision):
            raise ValueError("revision must be a positive int64 integer (decimal digits)")
        # Reject oversize digit strings before int() hits Python's digit limit.
        significant = revision.lstrip("0")
        if not significant or len(significant) > 19 or int(significant) > 2**63 - 1:
            raise ValueError("revision must be a positive int64 integer")
        record["revision"] = int(significant)
        if record["deleted"] not in ("true", "false"):
            raise ValueError("deleted must be true or false")
        record["deleted"] = record["deleted"] == "true"
        record["value"] = _number(record["value"], "value", nullable=True)
    elif cls is FeatureSpec:
        record["max_age_days"] = _number(record["max_age_days"], "max_age_days", nullable=True)
    elif cls is RollingSpec:
        record["window_days"] = _number(record["window_days"], "window_days")
    return cls(**record)


def _read_table(path, cls):
    expected = {field.name for field in fields(cls)}
    converted = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        # Track physical lines for diagnostics and blank records. A quoted
        # multi-line identifier, including its interior blank lines, stays intact.
        record_lines = []

        def lines():
            for line in stream:
                record_lines.append(line)
                yield line

        reader = csv.reader(lines(), strict=True)
        header = None
        try:
            for values in reader:
                blank = not "".join(record_lines).strip()
                record_lines.clear()
                if blank:
                    continue
                if header is None:
                    if len(values) != len(expected) or set(values) != expected:
                        raise ValueError(
                            f"{path.name}: expected columns {sorted(expected)} "
                            f"(header ends at physical line {reader.line_num})")
                    header = values
                    continue
                if len(values) != len(header):
                    raise ValueError(
                        f"{path.name} row {reader.line_num}: expected {len(header)} fields, got {len(values)}")
                try:
                    converted.append(_convert(dict(zip(header, values, strict=True)), cls))
                except (ValueError, TypeError) as error:
                    raise ValueError(f"{path.name} row {reader.line_num}: {error}") from error
        except csv.Error as error:
            raise ValueError(f"{path.name} row {reader.line_num}: malformed CSV quoting: {error}") from error
        except UnicodeError as error:
            raise ValueError(f"{path.name}: CSV must be UTF-8") from error
        if header is None:
            raise ValueError(f"{path.name}: expected columns {sorted(expected)} (no header found)")
    return converted


def load_csv_inputs(directory, *, rolling=False):
    """Load three exact-schema UTF-8 tables into validated JSON-shaped inputs.

    Scalar mode reads observations.csv, decisions.csv and specs.csv. Rolling
    mode replaces specs.csv with rolling_specs.csv. Identifiers stay strings;
    only an empty numeric cell means null. No pandas or output files are used.
    """
    directory = Path(directory)
    observations = _read_table(directory / "observations.csv", Observation)
    decisions = _read_table(directory / "decisions.csv", Decision)
    name, cls = ("rolling_specs", RollingSpec) if rolling else ("specs", FeatureSpec)
    specifications = _read_table(directory / f"{name}.csv", cls)
    validator = validate_rolling if rolling else validate
    observations, decisions, specifications = validator(observations, decisions, specifications)
    return {
        "data_kind": "user_supplied",
        "observations": [asdict(row) for row in observations],
        "decisions": [asdict(row) for row in decisions],
        name: [asdict(row) for row in specifications],
    }
