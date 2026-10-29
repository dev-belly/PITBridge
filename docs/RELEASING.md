# Reproduce a checked release

CI builds the source distribution first and builds its wheel from that archive.
On Linux Python 3.11/3.12 and Windows Python 3.12, `check_distribution.py` installs
the wheel without a package index into a fresh virtual environment. From a
directory outside the checkout it verifies package/runtime versions, generates
and semantically replays scalar/rolling JSON and CSV bundles, compares the CSV
results, and runs two 2,000-observation benchmark trials with the independent
oracle. The installed wheel also checks exact-cutoff versus one-microsecond-late
selection and rejects a seventh digit on all four scalar/rolling JSON/CSV CLI
routes before creating a report. The benchmark is an installation smoke check,
not a release performance claim.

The installed gate also runs both `init-csv` modes from that empty work
directory, builds and independently replays their reports, and compares their
result CSVs with the installed demos. It rejects a second initialization without
changing input bytes, then edits an arrival and verifies the changed scalar
selection. Publication requires this editable-starter evidence alongside the
existing timestamp, JSON/CSV replay and benchmark checks.

To reproduce from a clean checkout with no stale files in `dist` or `release`:

```bash
python -m pip install build
python -m build --outdir dist
python scripts/check_distribution.py dist --output installed-check.json
python scripts/release_artifacts.py prepare dist installed-check.json release --commit "$(git rev-parse HEAD)"
python scripts/release_artifacts.py verify release --commit "$(git rev-parse HEAD)"
```

In PowerShell, assign `$releaseCommit = git rev-parse HEAD` and pass
`--commit $releaseCommit` in the last two commands. A local commit binding is
meaningful only when the checkout is clean. Local preparation does not publish.
The scripts require exactly one current-version pure-Python wheel and source
archive, validate both package metadata records, require every installed replay
route and matching benchmark digests, and refuse an existing output directory.

## Publication

1. Update `pyproject.toml` and `pitbridge.__version__` together; add
   `docs/releases/vX.Y.Z.md`. Explain any replay or input compatibility change.
2. Review and merge the changes. The entire `CI` workflow must pass on the exact
   `main` push, including all OS/Python, pandas and Chrome jobs. Linux Python 3.12
   retains the five checked assets as `checked-distributions` for 30 days.
3. `Publish checked release` accepts only successful push runs from this
   repository's `main`. It checks out that run's exact SHA, downloads that run's
   artifact, and verifies the commit, version, exact file set, metadata, replay
   evidence and every SHA-256 digest. It publishes those files without a rebuild.

Pull requests and fork runs cannot trigger publication. Existing releases are
left in place; another release requires a version bump. Re-running the original
main CI can retry a failed publication. GitHub's workflow token creates the
version tag at the checked commit; no PyPI upload or registry credential is used.
Checksums detect changed bytes; they are not author signatures or proof that
external source data is truthful.
