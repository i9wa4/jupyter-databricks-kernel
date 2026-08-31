# Sync Benchmark

Use this workflow to compare file synchronization latency before and after sync
changes. It is manual because it needs a real Databricks workspace,
authentication, and a classic all-purpose cluster, but the local fixture and
mutations are deterministic.

Do not use a project example that reads or writes real tables, DBFS paths, S3
locations, or workspace data. The benchmark source tree below contains only
local Python files and one `pyproject.toml`.

## Prerequisites

- Databricks authentication is configured for the target workspace.
- `DATABRICKS_CLUSTER_ID` or the active Databricks profile selects a running or
  startable classic all-purpose cluster.
- The checkout dependencies are installed with `uv sync`.
- Public reports replace cluster IDs, host names, user names, service principal
  names, profile names, local absolute paths, and workspace URLs with stable
  labels such as `<cluster-a>` or `<profile-dev>`.

Set package-scoped debug logging so phase-level sync diagnostics are visible:

```bash
export JUPYTER_DATABRICKS_KERNEL_LOG_LEVEL=DEBUG
```

## Create The Fixture

Run these commands from the repository root. They replace only the benchmark
fixture under `.cache/sync-benchmark-fixture`.

```bash
rm -rf .cache/sync-benchmark-fixture
mkdir -p .cache/sync-benchmark-fixture/pkg
python - <<'PY'
from pathlib import Path

root = Path(".cache/sync-benchmark-fixture")
(root / "pyproject.toml").write_text(
    "[tool.jupyter-databricks-kernel.sync]\n"
    'source = "."\n'
    "use_gitignore = false\n"
    "compression_level = 1\n"
)
(root / "main.py").write_text(
    "from pkg.module_000 import value\n"
    "print(value())\n"
)
(root / "pkg" / "__init__.py").write_text("")
for index in range(100):
    body = f"def value():\n    return 'module-{index:03d}'\n"
    (root / "pkg" / f"module_{index:03d}.py").write_text(body)
PY
```

The fixture contains 103 synchronized files: one `pyproject.toml`, one
`main.py`, one package `__init__.py`, and 100 small module files.

Record the exact revision and sync configuration before every benchmark run:

```bash
git rev-parse --short HEAD
sed -n '1,20p' .cache/sync-benchmark-fixture/pyproject.toml
```

## Run The Persistent Benchmark

The warm no-change case must run in one Python process with one `FileSync`
instance and one executor. Separate CLI invocations create separate sync
lifecycles and do not measure the persistent no-change path.

```bash
python - <<'PY'
from __future__ import annotations

import shutil
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from jupyter_databricks_kernel.config import Config
from jupyter_databricks_kernel.executor import DatabricksExecutor
from jupyter_databricks_kernel.sync import FileSync

fixture = Path(".cache/sync-benchmark-fixture").resolve()
baseline = Path(".cache/sync-benchmark-fixture.baseline")
if baseline.exists():
    shutil.rmtree(baseline)
shutil.copytree(fixture, baseline)


def restore() -> None:
    if fixture.exists():
        shutil.rmtree(fixture)
    shutil.copytree(baseline, fixture)


def mutate_one_small_file() -> None:
    path = fixture / "pkg" / "module_001.py"
    path.write_text("def value():\n    return 'module-001-edited'\n")


def create_one_file() -> None:
    (fixture / "pkg" / "created.py").write_text("CREATED = True\n")


def delete_one_file() -> None:
    (fixture / "pkg" / "module_002.py").unlink()


def rename_one_file() -> None:
    (fixture / "pkg" / "module_003.py").rename(fixture / "pkg" / "renamed_003.py")


def change_several_files() -> None:
    for index in range(10, 20):
        path = fixture / "pkg" / f"module_{index:03d}.py"
        path.write_text(f"def value():\n    return 'module-{index:03d}-edited'\n")


def add_many_small_files() -> None:
    for index in range(200):
        (fixture / "pkg" / f"extra_{index:03d}.py").write_text(
            f"EXTRA_VALUE = {index}\n"
        )


def run_case(
    label: str,
    mutate: Callable[[], None] | None,
    *,
    runs: int = 5,
    persistent_warm: bool = False,
) -> None:
    totals: list[float] = []
    for run in range(1, runs + 1):
        restore()
        config = Config.load(fixture / "pyproject.toml")
        config.base_path = fixture
        sync = FileSync(config, f"bench-{label.replace(' ', '-')}-{run}")
        executor = DatabricksExecutor(config)
        try:
            if persistent_warm:
                sync.sync_and_setup(executor)
                started = time.perf_counter()
                result = sync.sync_and_setup(executor)
                total = time.perf_counter() - started
                stats = result
            else:
                if mutate is not None:
                    sync.sync_and_setup(executor)
                    mutate()
                stats = sync.sync_and_setup(executor)
                total = stats.total_duration if stats is not None else 0.0
            upload = stats.upload_duration if stats is not None else 0.0
            changed = stats.changed_files if stats is not None else 0
            deleted = stats.deleted_files if stats is not None else 0
            total_files = stats.total_files if stats is not None else 0
            source_size = stats.source_size if stats is not None else 0
            archive_size = stats.archive_size if stats is not None else 0
            chunks = stats.chunk_count if stats is not None else 0
            remote_calls = stats.remote_calls if stats is not None else 0
            totals.append(total)
            print(
                f"{label}\trun={run}\tpreparation_total_seconds={total:.6f}"
                f"\tupload_seconds={upload:.6f}\tchanged_files={changed}"
                f"\tdeleted_files={deleted}\ttotal_files={total_files}"
                f"\tsource_size_bytes={source_size}"
                f"\tarchive_size_bytes={archive_size}\tchunks={chunks}"
                f"\tremote_calls={remote_calls}"
            )
        finally:
            sync.cleanup()
            executor.destroy_context()
    print(f"{label}\tmedian_seconds={statistics.median(totals):.6f}")


cases: list[tuple[str, Callable[[], None] | None]] = [
    ("cold first sync", None),
    ("one small file changed", mutate_one_small_file),
    ("one file created", create_one_file),
    ("one file deleted", delete_one_file),
    ("one file renamed", rename_one_file),
    ("several small files changed", change_several_files),
    ("many small files added", add_many_small_files),
]

run_case("persistent warm no-change", None, persistent_warm=True)
for case_label, case_mutation in cases:
    run_case(case_label, case_mutation)
restore()
PY
```

## Reset Between Candidate Revisions

Before switching branches, changing sync code, or repeating a candidate run,
reset the fixture and remove the copied baseline:

```bash
rm -rf .cache/sync-benchmark-fixture .cache/sync-benchmark-fixture.baseline
```

Then recreate the fixture from the commands above. Keep the same cluster,
profile, Python environment, fixture counts, and sync configuration when
comparing revisions.

For a cold remote directory run, set a new extraction directory before starting
the Python benchmark process:

```bash
export JUPYTER_DATABRICKS_KERNEL_EXTRACT_DIR=/tmp/jdk-sync-benchmark-$(date +%s)
```

For a remote-state-missing run, restart the cluster or remove only the remote
benchmark extraction directory, then run the benchmark process again.

## Result Format

Record one row per case and revision. Report medians from at least five runs.

```text
Revision: <git-sha>
Cluster: <cluster-a>
Profile: <profile-dev>
Python: <version>
Sync config: source=., use_gitignore=false, compression_level=1
Fixture: 103 baseline files, 100 modules, many-file case adds 200 files

Case: persistent warm no-change
Median total: <ms>
Lifecycle: one FileSync instance, one DatabricksExecutor, one Python process

Case: one small file changed
Median total: <ms>
Upload total: <ms>
Discovery: <ms>
Change detection: <ms>
Archive creation: <ms>
Context setup: <ms>
Transfer: <ms>
Remote apply: <ms>
Path setup: <ms>
Preparation total: <ms>
Files: <changed> changed / <total> total
Deleted: <deleted>
Source size: <bytes-or-human-size>
Payload: <bytes-or-human-size> / <chunks> chunks
Remote calls: <count>
Mode: full
```

Include runner exit code and sync failure messages only when they are relevant
and sanitized. Do not include Databricks tokens, Jupyter connection secrets,
workspace URLs, cluster IDs, profile names, local absolute paths, or output that
contains private workspace data in public issue or PR comments.

## Decision Gate

Use the collected measurements before implementing incremental sync. If the
warm one-file edit case is dominated by Command Execution API round trips,
prefer round-trip consolidation before archive or diff complexity. If archive
creation or payload transfer remains dominant after low-risk fixes, then
prototype incremental sync behind an explicit fallback path.
