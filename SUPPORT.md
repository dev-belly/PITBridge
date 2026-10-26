# Support for PITBridge

Use [the late-correction example](examples/README.md), [CSV contract](docs/CSV_INPUTS.md) and [selection contract](docs/DATA_CONTRACT.md) to isolate a problem. After installation, replay the saved scalar and rolling evidence:

```bash
pitbridge verify --out demo
pitbridge verify-rolling --out demo/rolling
```

Use the existing [bug, feature or trial-feedback templates](https://github.com/dev-belly/PITBridge/issues/new/choose). Include the exact version/commit, OS/Python, command, input format and a minimal synthetic case. Two revisions and one decision are often enough: retain event, publication, ingestion and decision times, revision identity and units. For rolling results, include the window boundary and expected contributors.

If using the optional pandas example, report its pandas version separately; pandas is not a core runtime requirement. Installation or release-asset problems should identify the full source/wheel URL used. See [CONTRIBUTING.md](CONTRIBUTING.md) for distribution checks and [SECURITY.md](SECURITY.md) for suspected vulnerabilities. Keep private invoices, borrower identifiers and credentials out of public reports.
