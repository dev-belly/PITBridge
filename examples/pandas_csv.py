"""Optional CSV adapter for the synthetic late-correction example."""

import csv
from dataclasses import asdict
import json
from pathlib import Path
import re

from pitbridge import Decision, FeatureSpec, Observation, build_snapshot, reference_snapshot


FIXTURE = Path(__file__).parent / "csv"
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def revision_value(value):
    # Never round a revision through binary64, or accept bool as an integer.
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError("revision must be a positive int64 integer (decimal digits)")
    # Leading zeroes do not change the value. Bound significant digits before
    # int() so long CSV cells keep the same contract on every Python version.
    significant = value.lstrip("0")
    if not significant or len(significant) > 19:
        raise ValueError("revision must be a positive int64 integer")
    revision = int(significant)
    if not 1 <= revision <= 2**63 - 1:
        raise ValueError("revision must be a positive int64 integer")
    return revision


def deleted_value(value):
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("deleted must be true or false")


def optional_number(value, name):
    # Only an empty CSV cell means null; NA-like text is not missing data.
    if value == "":
        return None
    # float() also accepts underscores, whitespace and non-ASCII digits. Keep
    # this example's numeric text contract aligned with the native CSV importer.
    if not isinstance(value, str) or not _NUMBER.fullmatch(value):
        raise ValueError(f"{name} must be a decimal number or an empty cell")
    return float(value)


def load_inputs(directory=FIXTURE):
    import pandas as pd  # Optional example dependency, never imported by PITBridge.

    def rows(name, cls):
        path = Path(directory) / f"{name}.csv"
        expected = set(cls.__dataclass_fields__)
        # Parse one text snapshot before creating a DataFrame: read_csv can infer
        # an index from extra fields and silently drop it from to_dict(records).
        with path.open(encoding="utf-8-sig", newline="") as handle:
            physical_lines = list(handle)
        reader = csv.reader(physical_lines, strict=True)
        header = None
        records, end_lines = [], []
        previous_line = 0
        try:
            for values in reader:
                end_line = reader.line_num
                raw_record = "".join(physical_lines[previous_line:end_line])
                previous_line = end_line
                # Match pandas' blank-line behavior without removing blank
                # physical lines inside a quoted multi-line field.
                if not raw_record.strip():
                    continue
                if header is None:
                    if len(values) != len(expected) or set(values) != expected:
                        raise ValueError(
                            f"{path.name}: expected columns {sorted(expected)} "
                            f"(header ends at physical line {end_line})")
                    header = values
                    continue
                if len(values) != len(header):
                    raise ValueError(
                        f"{path.name} row {end_line}: expected {len(header)} fields, "
                        f"got {len(values)}")
                records.append(values)
                end_lines.append(end_line)
        except csv.Error as exc:
            raise ValueError(
                f"{path.name} row {reader.line_num}: malformed CSV quoting: {exc}") from exc
        if header is None:
            raise ValueError(f"{path.name}: expected columns {sorted(expected)} (no header found)")
        table = pd.DataFrame(records, columns=header, dtype=str)
        converted = []
        for line, fields in zip(end_lines, table.to_dict(orient="records"), strict=True):
            try:
                if cls is Observation:
                    fields["revision"] = revision_value(fields["revision"])
                    fields["deleted"] = deleted_value(fields["deleted"])
                    fields["value"] = optional_number(fields["value"], "value")
                elif cls is FeatureSpec:
                    fields["max_age_days"] = optional_number(fields["max_age_days"], "max_age_days")
                # Dataclasses validate timestamps, identifiers and missing values.
                converted.append(cls(**fields))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path.name} row {line}: {exc}") from exc
        return converted

    return rows("observations", Observation), rows("decisions", Decision), rows("specs", FeatureSpec)


def main():
    inputs = load_inputs()
    snapshots = build_snapshot(*inputs)
    if snapshots != reference_snapshot(*inputs):
        raise RuntimeError("SQL and independent temporal replay disagree")
    expected = [(None, None, "not_available"),
                ("invoice-v1", 100000.0, "selected"),
                ("invoice-v2", 135000.0, "selected")]
    if [(r.record_id, r.value, r.status) for r in snapshots] != expected:
        raise RuntimeError("CSV selections differ from the canonical late-correction example")
    print(json.dumps([asdict(row) for row in snapshots], indent=2))


if __name__ == "__main__":
    main()
