# ArchiveBox CI Observatory

Static GitHub Pages dashboard for the five authoritative project CI workflows:

| Project | Workflow | Package registry | Container registry |
| --- | --- | --- | --- |
| `abxbus` | `ci.yml` | PyPI | — |
| `abxpkg` | `tests.yml` | PyPI | — |
| `abx-plugins` | `test-parallel.yml` | PyPI | — |
| `abx-dl` | `ci.yml` | PyPI | Docker Hub |
| `archivebox` | `ci.yml` | PyPI | Docker Hub |

The collector is read-only. It never checks out a member repository, dispatches a workflow, or reruns a test. It reads existing GitHub workflow runs, job and step timings, a bounded number of job logs, PyPI JSON metadata, and Docker Hub tag metadata. Compact top-job timing summaries and the ten slowest test-job log candidates are retained for historical runs, while parsed test-log summaries from the prior Pages deployment are carried forward.

## Local preview

```bash
GH_TOKEN="$(gh auth token)" uv run --no-project --python 3.13 evals/collect.py \
    --runs-per-project 2 \
    --job-metadata-budget 10 \
    --log-budget 5
uv run --no-project --python 3.13 -m http.server 4173 --directory evals/site
```

Open <http://127.0.0.1:4173/>. The generated `evals/site/data.json` is intentionally ignored.

## Publication and permissions

`.github/workflows/evals-dashboard.yml` publishes `evals/site/` to this repository's GitHub Pages site on relevant pushes, manual dispatch, and twice per hour. GitHub's scheduled workflows do not support a two-minute interval; the page checks for newly deployed JSON every two minutes without consuming a runner.

Scheduled and push refreshes inspect at most 20 new run job lists and ten new logs. A manual dispatch defaults to 250 job lists and 60 logs, providing resumable history backfills across all five projects without making every scheduled run expensive.

Repository metadata and PyPI/Docker data work with the normal token. Compact test counts, slowest-test details, and TTFI are parsed from Actions job logs, which require a fine-grained `GH_EVALS_TOKEN` Actions secret with read-only **Actions** and **Metadata** access to these five public repositories. Without it the site still publishes, but log-derived cells remain explicitly unreported.

## Optional TTFI reporting

GitHub does not expose Python import timing in run metadata. The reusable composite action in this monorepo emits one structured line from a package environment that a member CI job already created:

```yaml
- name: Report package import timing
  uses: ArchiveBox/monorepo/.github/actions/report-ci-evals@main
  with:
    import-name: abx_plugins
```

Use `abxbus`, `abxpkg`, `abx_plugins`, `abx_dl`, or `archivebox` as appropriate. The action performs one real cold import with the existing environment and prints both `ABX_EVALS {…}` and the package version. It does not install dependencies or repeat tests. Until a project opts into this single step, TTFI remains `—` rather than being inferred from an unrelated step duration.

## Metric meanings

- **Slowest job** is the longest individual GitHub Actions job in a workflow run. It is the default trend because it directly identifies the job responsible for a spike.
- **Runner time** is the sum of all job durations, exposing increases in total billed work even when parallelism keeps wall time flat.
- **Full CI** is wall-clock time from workflow start to the final subjob completion, including parallelism.
- **Tests** is the number of test executions reported in parsed pytest, Rust, Go, or JavaScript summaries. Matrix executions are counted because they are real CI work.
- **Avg / test** is full CI wall time divided by measured test executions.
- **Slowest pytest** is the largest per-test duration explicitly emitted by an existing test runner; no value is guessed when durations are absent.
- **PyPI size** is the largest wheel in the current release. The chart uses each release's largest wheel.
- **Docker build** is the longest reported image-build step in the run, reflecting the critical-path architecture.
- **Docker size** is Docker Hub's compressed `full_size` for the newest `latest`, `dev`, or `main` tag.
- **TTFI** is a real cold `importlib.import_module(package)` duration followed by reading and printing `package.__version__` (or `VERSION`).
