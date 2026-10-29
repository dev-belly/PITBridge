"""Editable synthetic input tables available from the installed package."""

import csv
from dataclasses import fields
import io
from pathlib import Path
import tempfile

from .core import Decision, FeatureSpec, Observation
from .csv_inputs import load_csv_inputs
from .demo import demo_inputs
from .rolling import RollingSpec
from .rolling_bundle import rolling_demo_inputs


def _table(records, cls):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=[field.name for field in fields(cls)], lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(
        {key: str(value).lower() if isinstance(value, bool) else value
         for key, value in row.items()}
        for row in records
    )
    return stream.getvalue()


def write_csv_starter(directory, *, rolling=False):
    """Create a validated scalar/rolling case in a new directory, never overwrite.

    The existing demo functions are the sole fixture source. CSV intake retains
    its user_supplied route label; the generated case is explicitly synthetic.
    """
    target = Path(directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError("Choose a new input directory; existing paths are never overwritten")
    data = rolling_demo_inputs() if rolling else demo_inputs()
    spec, cls = ("rolling_specs", RollingSpec) if rolling else ("specs", FeatureSpec)
    tables = {
        "observations.csv": _table(data["observations"], Observation),
        "decisions.csv": _table(data["decisions"], Decision),
        f"{spec}.csv": _table(data[spec], cls),
    }
    command, verify = ("aggregate", "verify-rolling") if rolling else ("build", "verify")
    exercise = (
        "The 30-day sum for SME-A is 1500, 4300 and 6300 on February 10, 11 and 12.\n"
        "Each selected contribution remains visible in members.csv.\n"
        if rolling else
        "For SME-A-4, tax/invoice_revenue selects tax-a-v2 with value 180000.\n"
        "Move that row's ingested_at to 2026-04-03T00:00:00Z in observations.csv;\n"
        "SME-A-4 then selects tax-a-v1 with value 100000. Keep a new output per trial.\n"
    )
    readme = (
        "# Editable PITBridge input case\n\n"
        "All records and values in these tables are SYNTHETIC; no real borrower data.\n"
        "CSV reports use the user_supplied intake label, which does not authenticate\n"
        "a source or turn this fixture into observed data.\n\n"
        "From this input directory, use the Python environment with PITBridge installed:\n\n"
        f"    python -m pitbridge {command} --csv-dir . --out ../pitbridge-{command}-report\n"
        f"    python -m pitbridge {verify} --out ../pitbridge-{command}-report\n\n"
        "Choose a new report directory for later trials.\n\n"
        + exercise
        + "\nKeep timezone-aware timestamps, lowercase true/false and exact headers.\n"
        "An empty value is valid only for a tombstone (deleted=true).\n"
        "Input contract: https://github.com/dev-belly/PITBridge/blob/main/docs/CSV_INPUTS.md\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pitbridge-inputs-", dir=target.parent) as temporary:
        staged = Path(temporary) / "case"
        staged.mkdir()
        for name, content in {**tables, "README.md": readme}.items():
            (staged / name).write_text(content, encoding="utf-8", newline="")
        load_csv_inputs(staged, rolling=rolling)
        if target.exists() or target.is_symlink():
            raise FileExistsError("Choose a new input directory; existing paths are never overwritten")
        staged.rename(target)
    # Keep stdout ASCII even when a Windows input path contains non-ASCII text.
    return {
        "status": "created", "data_kind": "synthetic",
        "mode": "rolling" if rolling else "scalar",
        "observations": len(data["observations"]), "decisions": len(data["decisions"]),
        "specifications": len(data[spec]), "files": [*tables, "README.md"],
    }
