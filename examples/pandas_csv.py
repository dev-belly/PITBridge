"""Optional CSV adapter for the synthetic late-correction example."""

from dataclasses import asdict
import json
from pathlib import Path
import re

from pitbridge import Decision, FeatureSpec, Observation, build_snapshot, reference_snapshot


FIXTURE = Path(__file__).parent / "csv"


def revision_value(value):
    # Never round a revision through binary64, or accept bool as an integer.
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError("revision must be a positive int64 integer (decimal digits)")
    revision = int(value)
    if not 1 <= revision <= 2**63 - 1:
        raise ValueError("revision must be a positive int64 integer")
    return revision


def deleted_value(value):
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("deleted must be true or false")


def optional_number(value):
    # Only an empty CSV cell means null; NA-like text is not missing data.
    return None if value == "" else float(value)


def load_inputs(directory=FIXTURE):
    import pandas as pd  # Optional example dependency, never imported by PITBridge.

    def rows(name, cls):
        path = Path(directory) / f"{name}.csv"
        table = pd.read_csv(path, dtype=str, keep_default_na=False)
        expected = set(cls.__dataclass_fields__)
        if set(table.columns) != expected:
            raise ValueError(f"{path.name}: expected columns {sorted(expected)}")
        converted = []
        for line, fields in enumerate(table.to_dict(orient="records"), 2):
            try:
                if cls is Observation:
                    fields["revision"] = revision_value(fields["revision"])
                    fields["deleted"] = deleted_value(fields["deleted"])
                    fields["value"] = optional_number(fields["value"])
                elif cls is FeatureSpec:
                    fields["max_age_days"] = optional_number(fields["max_age_days"])
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
