# Reproducing the frozen study

## Two artifact sizes

The Git repository provides the technical reports, editable report sources, frozen evaluation code, a synthetic example, and the public download/replay scripts. The complete data package is a versioned GitHub Release attachment. It contains the 42 drawing pages, historical prompts, references, 723 response files, missing-slot records, exact scientific scorers, and expected tables.

The dataset and historical responses are not tracked in ordinary Git history. Download them with `python scripts/download_release.py --output artifacts/reproducibility`. The downloader pins the version, SHA-256, and archive root from `docs/release.json`, rejects path traversal and archive symlinks, and refuses to overwrite an existing directory.

### HTTPS certificate setup

The one-time download needs a working trusted CA store in Python. On a Mac whose Python installation has no configured CA bundle, the verified local download used `SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/download_release.py --output artifacts/reproducibility`. Use that path only where the system bundle exists; otherwise configure your Python installation's trusted certificate store. Offline scoring does not use HTTPS.

## Offline execution

Use Python 3.13 and the pinned `requirements.txt`. After downloading the package, scoring itself is offline:

```sh
python scripts/reproduce.py --package artifacts/reproducibility --output runs/replay01 --tables runs/tables01
```

The wrapper runs the package's frozen-output scorer, rebuilds the principal tables, and verifies all 730 scientific signatures plus the complete `MAJOR_TABLES.json` and `PAIRED_BOOTSTRAP.json` objects against their frozen counterparts. It does not query a model or repair a response. Output directories must be new.

The underlying commands are:

```sh
python -B artifacts/reproducibility/run_reproduction.py --output runs/replay01 --workers 2
python -B artifacts/reproducibility/build_tables.py --results runs/replay01/REPLAY_RESULTS.json --output runs/tables01
python -B artifacts/reproducibility/verify_replay.py --replay runs/replay01 --tables runs/tables01
```

Allow approximately 160 MB for the unpacked package and 160 MiB for one new replay. Fresh scoring is approximately 43 MB in the tested environment. The bundled native dependency fallback targets CPython 3.13 on macOS arm64 only; Linux should use installed dependencies. `TOPOWORLD_DISABLE_VENDOR=1` explicitly selects an installed environment.

## Validation evidence

| Environment | Public-release evidence |
|---|---|
| macOS arm64, Python 3.13 | Full 730/730 replay and exact principal tables: [receipt](validation/macOS_run_receipt.json) |
| Linux x86-64, Python 3.13.18 | Full 730/730 replay and exact principal tables: [receipt](validation/Linux_run_receipt.json), [successful run](https://github.com/lijincheng494gmail/TopoWorld-Eval/actions/runs/42242415082) |
| Windows | Unsupported by the frozen Unix resource-limit worker; not verified |

On 6 November 2026, GitHub Actions on Ubuntu 24.04 (Linux x86-64, Python 3.13.18) downloaded the published ZIP, matched all 730 scientific signatures, and regenerated both principal tables without differences. The evaluated source commit is recorded in the receipt. This adds independent platform validation without changing the frozen ZIP.

The public GitHub workflow runs the small software examples on pushes. Its explicitly dispatched full-replay mode downloads the pinned public Release, runs all retained allocations on Ubuntu 24.04, compares both main table objects, and saves a small environment/commit/Release receipt. No API credentials or model calls are involved.

## Preserved scientific boundary

Evaluator 2.2.1, executable-world Schema, condition-specific scoring functions, reference labels, image pixels, and exported response bytes retain their scientific version. The public derivative records the source artifact hashes in its provenance and refreshes a package manifest for the published bytes. Release changes are documentation, distribution, and explicit verification aids.

There are 730 assigned stages, 723 existing reply files (one empty), and seven missing allocations. The export includes 695 byte-exact originals and 28 previously documented derivatives with only length-preserving personal-path masking. No malformed JSON is repaired or rewritten. Frozen failures remain failures.

The 730/730 acceptance result means that deterministic scoring agrees with the retained record, including failures. It does not reproduce proprietary model generation or establish that all answers/worlds are correct. Historical execution metadata describe the recorded environment; offline scoring cannot newly verify a hidden neural checkpoint or reread unshared private host sessions.

## Reading code without the data download

`evaluation/evaluator/` contains the frozen geometry implementation and Schema; `evaluation/frozen/` contains the preserved condition-specific scorers. The full replay entry point also needs the Release data folders. Run `python scripts/check_example.py` for a self-contained software demonstration from the Git tree alone.

For a generic new world, this is an evaluation instrument rather than a generation service. The example scripts load JSON as data; do not execute model-generated code. Reference task obligations and evidence qualification are still needed to interpret a new scientific score.
