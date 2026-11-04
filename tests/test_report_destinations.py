"""Repeated CLI/library writes must preserve existing evidence and user files."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pitbridge.bundle import write_bundle
from pitbridge.cli import main
from pitbridge.csv_starter import write_csv_starter
from pitbridge.demo import demo_inputs
from pitbridge.rolling_bundle import rolling_demo_inputs, write_rolling_bundle


MODES = (("scalar", demo_inputs, write_bundle, "demo", "build"),
         ("rolling", rolling_demo_inputs, write_rolling_bundle, "rolling-demo", "aggregate"))


class ReportDestinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        self.assertEqual((code, stdout.getvalue()), (2, ""))
        self.assertNotIn("Traceback", stderr.getvalue())
        return stderr.getvalue()

    def symlink(self, target, source, *, directory=False):
        try:
            target.symlink_to(source, target_is_directory=directory)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows link creation requires Developer Mode or elevated privileges")
            raise

    def test_changed_data_cannot_replace_an_existing_scalar_or_rolling_report(self):
        for mode, factory, writer, _, _ in MODES:
            with self.subTest(mode=mode):
                target = self.root / mode
                target.mkdir()  # Existing empty directories remain supported.
                data = factory()
                writer(data, target)
                before = {p.name: p.read_bytes() for p in target.iterdir()}
                next(r for r in data["observations"] if not r.get("deleted", False))["value"] += 1
                with self.assertRaisesRegex(FileExistsError, "new or empty report"):
                    writer(data, target)
                self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)

    def test_all_six_cli_input_routes_leave_nonempty_destinations_untouched(self):
        for mode, factory, writer, demo, command in MODES:
            source = self.root / f"{mode}-source"
            writer(factory(), source)
            tables = self.root / f"{mode}-tables"
            write_csv_starter(tables, rolling=mode == "rolling")
            for route in ([], ["--inputs", str(source / "inputs.json")], ["--csv-dir", str(tables)]):
                target = self.root / f"{mode}-foreign"
                target.mkdir(exist_ok=True)
                (target / "notes.txt").write_bytes(b"keep my review notes")
                with self.subTest(mode=mode, route=route):
                    error = self.cli([command if route else demo, *route, "--out", str(target)])
                    self.assertIn("new or empty report", error)
                    self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()},
                                     {"notes.txt": b"keep my review notes"})

    def test_regular_file_destinations_are_not_replaced(self):
        for mode, factory, writer, _, _ in MODES:
            target = self.root / mode
            target.write_bytes(b"keep this source file")
            with self.subTest(mode=mode), self.assertRaises(FileExistsError):
                writer(factory(), target)
            self.assertEqual(target.read_bytes(), b"keep this source file")

    def test_directory_file_and_dangling_destination_links_are_refused(self):
        directory = self.root / "outside-directory"
        directory.mkdir()
        source = self.root / "outside-source"
        source.write_bytes(b"source bytes")
        for mode, factory, writer, _, _ in MODES:
            for kind, destination in (("directory", directory), ("file", source),
                                      ("dangling", self.root / "absent")):
                target = self.root / f"{mode}-{kind}"
                self.symlink(target, destination, directory=kind == "directory")
                before = target.readlink()
                with self.subTest(mode=mode, kind=kind), self.assertRaises(FileExistsError):
                    writer(factory(), target)
                self.assertEqual(target.readlink(), before)
        self.assertEqual(list(directory.iterdir()), [])
        self.assertEqual(source.read_bytes(), b"source bytes")

    def test_an_existing_member_link_cannot_redirect_a_report_write(self):
        outside = self.root / "outside.csv"
        outside.write_bytes(b"valuable data")
        for mode, factory, writer, _, _ in MODES:
            target = self.root / mode
            target.mkdir()
            link = target / "inputs.json"
            self.symlink(link, outside)
            with self.subTest(mode=mode), self.assertRaises(FileExistsError):
                writer(factory(), target)
            self.assertEqual(list(target.iterdir()), [link])
            self.assertEqual(outside.read_bytes(), b"valuable data")

    def test_a_member_arriving_after_preflight_is_not_truncated(self):
        original = Path.open
        for mode, _, _, demo, _ in MODES:
            target = self.root / mode
            member = "snapshots.csv" if mode == "scalar" else "features.csv"

            def arriving(path, mode="r", *args, target=target, member=member, **kwargs):
                if path.parent == target and path.name == member and mode == "x":
                    with original(path, "xb") as handle:
                        handle.write(b"concurrent file")
                return original(path, mode, *args, **kwargs)

            with self.subTest(mode=mode), patch.object(Path, "open", arriving):
                self.cli([demo, "--out", str(target)])
            self.assertEqual((target / member).read_bytes(), b"concurrent file")
            self.assertFalse((target / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
