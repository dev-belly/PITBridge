"""Validate the saved first-trial notebook and execute its ordinary Python cells."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

INSTALL_TAG = "pitbridge-install"
ROOT = Path(__file__).resolve().parents[1]


def read_notebook(path: Path) -> list[dict]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    if notebook.get("nbformat") != 4 or notebook.get("nbformat_minor") != 5:
        raise ValueError("Expected notebook format 4.5")
    cells = notebook.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValueError("Expected a nonempty notebook cell list")
    identifiers = set()
    code_cells = []
    for cell in cells:
        identity = cell.get("id", "")
        if not isinstance(identity, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", identity
        ):
            raise ValueError("Every notebook cell needs a valid stable ID")
        if identity in identifiers:
            raise ValueError(f"Duplicate cell ID: {identity}")
        identifiers.add(identity)
        source = cell.get("source")
        if not isinstance(source, list) or not all(
            isinstance(line, str) for line in source
        ):
            raise ValueError(f"Invalid source in cell {identity}")
        if not isinstance(cell.get("metadata"), dict):
            raise ValueError(f"Invalid metadata in cell {identity}")
        if cell.get("cell_type") == "code":
            if cell.get("execution_count") is not None or cell.get("outputs") != []:
                raise ValueError(f"Saved code outputs must be cleared: {identity}")
            compile("".join(source), f"{path.name}:{identity}", "exec")
            code_cells.append(cell)
        elif cell.get("cell_type") != "markdown":
            raise ValueError(f"Unexpected cell type: {identity}")
    installation = [
        cell for cell in code_cells if INSTALL_TAG in cell["metadata"].get("tags", [])
    ]
    if len(installation) != 1 or installation[0] is not code_cells[0]:
        raise ValueError("Exactly the first code cell must carry the installation tag")
    return code_cells


def check(path: Path, *, run_install: bool = False) -> dict:
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ is required")
    cells = read_notebook(path)
    if run_install:
        if (
            sys.prefix == sys.base_prefix
            or importlib.util.find_spec("pitbridge") is not None
        ):
            raise ValueError(
                "Use --run-install only in a fresh virtual environment "
                "without PITBridge"
            )
    namespace = {"__name__": "__main__"}
    executed = 0
    for cell in cells:
        if INSTALL_TAG in cell["metadata"].get("tags", []) and not run_install:
            print(
                "Skipping pinned installation cell; "
                "checking the current interpreter's package."
            )
            continue
        exec(
            compile("".join(cell["source"]), f"{path.name}:{cell['id']}", "exec"),
            namespace,
        )
        executed += 1
    if run_install:
        origin = Path(namespace["pitbridge"].__file__).resolve()
        if not origin.is_relative_to(Path(sys.prefix).resolve()):
            raise ValueError(
                f"PITBridge was imported from outside the new environment: {origin}"
            )
    return {
        "status": "verified",
        "code_cells_executed": executed,
        "installation_executed": run_install,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--notebook", type=Path, default=ROOT / "examples/decision_time.ipynb"
    )
    parser.add_argument(
        "--run-install",
        action="store_true",
        help="Execute the pinned install cell, only in a fresh virtual environment",
    )
    args = parser.parse_args()
    print(json.dumps(check(args.notebook, run_install=args.run_install), indent=2))
