# Serverless Execution Backend Investigation

Research date: 2026-05-24.
Official reference review date: 2026-05-27.

Reference scope: use Databricks AWS English documentation where an AWS-scoped
page exists. The REST API reference pages are official Databricks API
references; they are used for API details that do not have AWS-scoped reference
URLs.

## Recommendation

Do not replace the current classic all-purpose cluster backend with Databricks
serverless compute.

Serverless compute can complement this project for specific non-interactive
paths, but it is not a drop-in backend for the current Jupyter kernel contract.
The current kernel and runner rely on the Databricks Command Execution API,
which creates a stateful execution context on a configured `cluster_id` and then
executes sequential Python commands in that context. The official Databricks
Command Execution API reference documents that it runs commands on running
Databricks clusters, supports only classic all-purpose clusters, and does not
support serverless compute.

Recommended path:

1. Keep the default Jupyter kernel and current runner behavior on classic
   all-purpose clusters.
2. Consider a separate SQL-only backend using the Statement Execution API and a
   SQL warehouse ID.
3. Consider a separate batch backend for `databricks-run`, with compatibility
   alias support for `run-py`, `run-db-py`, and `run-ipynb`, using serverless
   Lakeflow Jobs if file staging, dependency configuration, timeout/cancel
   handling, cleanup, and output capture are redesigned for workspace files,
   Unity Catalog volumes, cloud object storage, or Git-backed tasks.
4. Defer a serverless replacement for interactive notebook execution until
   Databricks provides a public stateful command/session API for serverless
   Python execution, or until the project intentionally changes semantics to a
   Spark Connect style model.

## Current Backend Contract

The current backend in `src/jupyter_databricks_kernel/executor.py` depends on:

- `Config.cluster_id`.
- `WorkspaceClient.command_execution.create(...)`.
- `WorkspaceClient.command_execution.execute(...)`.
- A reusable `context_id` that preserves Python process state across sequential
  cells.
- Cluster driver file staging through the existing sync path before execution.

Those properties fit the current Jupyter kernel behavior: a user can run
multiple cells in order and expect Python variables, imports, current working
directory setup, and synchronized project files to remain available in the
remote execution context.

## Serverless-Capable Surfaces

| Surface                                    | Serverless fit                                | Useful for this project                 | Main limitation                                                     |
| ------------------------------------------ | --------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------- |
| Command Execution API                      | No                                            | Current kernel and runner backend       | Classic all-purpose clusters only.                                  |
| Statement Execution API                    | Yes, through SQL warehouses                   | SQL-only execution path                 | SQL statements only; no Python state, magics, or synchronized files. |
| Lakeflow Jobs / Jobs API                   | Yes, for supported task types                 | Batch script or notebook runs           | Job/task lifecycle, not low-latency per-cell execution.             |
| Python script task on serverless Jobs      | Yes, through Jobs/Lakeflow serverless compute | Single-file batch `databricks-run` path | Requires staging an accessible file and capturing job-run output.    |
| Serverless notebooks in Databricks UI      | Yes                                           | Evidence for interactive support        | UI flow, not a public Command Execution equivalent.                 |
| Spark Connect / Databricks Connect style   | Serverless uses Spark Connect APIs            | Possible future separate mode           | Python runs locally; only Spark operations execute remotely.         |

## API Findings

### Command Execution API

The Command Execution API is the only current API surface in this project that
matches stateful cell-by-cell Python execution. It creates an execution context
and runs commands inside that context. It is not a serverless API.

Source:
<https://docs.databricks.com/api/workspace/commandexecution>

### Statement Execution API

The Statement Execution API runs SQL statements on a SQL warehouse. It supports
synchronous, asynchronous, and hybrid polling behavior through `wait_timeout`
and `on_wait_timeout`. It can return inline JSON results for small result sets
or external links for larger result sets.

This is viable for a SQL-only companion backend when the user configures a
`warehouse_id`. It does not satisfy the existing Python kernel semantics.

Sources:
<https://docs.databricks.com/aws/en/dev-tools/sql-execution-tutorial>
<https://docs.databricks.com/api/workspace/statementexecution>

### Lakeflow Jobs / Jobs API

Serverless compute for workflows supports job tasks such as notebooks, Python
scripts, dbt, Python wheels, and JAR tasks. Databricks documents that Jobs API,
Declarative Automation Bundles, and the Databricks SDK for Python can automate
serverless jobs.

This is viable for batch execution, especially for runner commands that do not
need interactive state. It is not a good fit for a Jupyter kernel cell loop.
Serverless jobs also have workload-specific behavior: standard performance mode
can have several minutes of startup latency, performance optimized mode is
faster, and serverless auto-optimization can retry failed tasks unless disabled.
The Jobs API exposes serverless job examples with `notebook_task` and
`spark_python_task` tasks, and serverless Python script, Python wheel, and dbt
tasks require an `environment_key` in the task settings.

Sources:
<https://docs.databricks.com/aws/en/jobs/run-serverless-jobs>
<https://docs.databricks.com/api/workspace/jobs/create>
<https://docs.databricks.com/api/workspace/jobs/submit>

### Python Single-File Batch Execution

A narrow serverless Python feature is plausible as batch execution, not as a
kernel backend. A runner such as
`databricks-run --backend serverless-job script.py` could stage one Python file
to a Databricks-accessible location, submit a serverless Jobs task with
`spark_python_task.python_file`, poll the run, and return status plus captured
logs or run output.

The first version should be intentionally constrained:

- One self-contained Python file.
- No automatic project sync.
- No persistent Python variables across runs.
- No interactive `input()` prompts.
- Dependencies configured through a serverless job environment or supported
  library locations.
- Output captured from the job run, subject to Jobs API and serverless logging
  behavior.
- Cleanup for any uploaded workspace file, volume file, or temporary job
  object.

Databricks documents that Python script tasks run a Python file and require the
script to be uploaded to a location accessible to the job author. For source
storage, Databricks recommends workspace files for Python scripts, and also
documents DBFS/S3, Unity Catalog volumes, cloud object storage, and Git-backed
sources. For serverless compute, the task uses the Environment and Libraries
field to select or create an environment.

Sources:
<https://docs.databricks.com/aws/en/jobs/python-script>
<https://docs.databricks.com/aws/en/files/workspace>
<https://docs.databricks.com/aws/en/files/files-recommendations>

### Notebook Batch Execution

Serverless notebook execution is also plausible as batch execution through a
Jobs notebook task. The notebook must be in a location accessible to the job,
such as a workspace notebook or Git-backed source. This maps to whole-notebook
execution, not Jupyter kernel semantics, and notebook job output has documented
cell output size limits.

Sources:
<https://docs.databricks.com/aws/en/jobs/notebook>
<https://docs.databricks.com/aws/en/jobs/run-serverless-jobs>

### Serverless Notebooks

Databricks notebooks can attach to serverless compute in the Databricks UI when
the workspace supports serverless interactive compute. This confirms that
interactive serverless notebooks exist, but the documented flow is a UI compute
selection flow, not a public API with the same `create_context`, `execute`, and
`destroy_context` contract as Command Execution.

Source:
<https://docs.databricks.com/aws/en/compute/serverless/notebooks>

## Tradeoffs Against Classic All-Purpose Clusters

### Startup latency

Classic all-purpose clusters have high startup latency when stopped, but once a
cluster and command execution context are running, subsequent cells can reuse
that context. This project already documents a 5-6 minute first execution when
the configured cluster is stopped.

Serverless jobs avoid user-managed cluster provisioning, but Databricks
documents that standard performance mode can tolerate startup latency of 4-6
minutes depending on availability and scheduling. Performance optimized mode is
faster, but it consumes more compute than standard performance mode.

Statement Execution latency depends on the target SQL warehouse. It is a better
fit for SQL query execution than for Python notebook cells.

### Cost model

Classic all-purpose clusters can incur idle cost while running. Serverless
compute minimizes idle infrastructure management and Databricks provides
serverless usage policies and billable usage system table reporting for
workflow cost monitoring. Exact pricing is cloud, region, SKU, and workload
dependent and should not be encoded in this project.

### Languages and APIs

The current command execution surface can run Python commands in a persistent
context. Serverless compute has stricter language and API limits. Databricks
documents that serverless notebooks do not support Scala or R, serverless uses
Spark Connect APIs, Spark RDD APIs are not supported, and Spark Connect can
change analysis and name-resolution timing.

Source:
<https://docs.databricks.com/aws/en/compute/serverless/limitations>

### Session and state lifecycle

The core blocker is state lifecycle. A Jupyter kernel needs sequential cells to
share Python state. Command Execution exposes that model with a `context_id`.
Statement Execution exposes statement IDs and SQL result lifecycles. Jobs expose
job and task runs. Neither exposes the same mutable Python REPL state required
by this kernel.

Serverless limitations also affect stateful notebook assumptions: global temp
views are not supported, metadata can be cached in serverless compute sessions,
and clearing that state requires resetting the serverless compute resource or
starting a new session.

### File staging

The current project syncs local files to the cluster driver node and runs code
from the extracted local path. Serverless compute has different storage
constraints: DBFS access is limited, Unity Catalog volumes or workspace files
are recommended, and compute-scoped libraries and init scripts are not
supported. Workspace files are useful for small code assets, but serverless has
workspace file caveats such as executor read/write limits and unsupported
`dbutils.fs` access to workspace files. Any serverless batch backend would need
a separate staging design.

Sources:
<https://docs.databricks.com/aws/en/compute/serverless/limitations>
<https://docs.databricks.com/aws/en/files/workspace>
<https://docs.databricks.com/aws/en/files/files-recommendations>

## Notebook-Style Execution Blockers

- No serverless support in the Command Execution API.
- No documented public serverless API that creates a reusable Python execution
  context equivalent to `context_id`.
- SQL warehouses can execute SQL but cannot run arbitrary Python cells.
- Jobs can run notebooks and Python scripts on serverless compute, but they are
  batch runs, not per-cell Jupyter kernel execution.
- Serverless notebook limitations exclude Scala and R notebooks, RDD APIs,
  Spark UI access, Spark logs, compute-scoped libraries, init scripts, and
  environment variables.
- Current file synchronization assumes a cluster driver filesystem, which does
  not map cleanly to serverless compute.

## Can Serverless Run Alongside Interactive Clusters?

Yes, as a complement with explicit routing.

Potential routing model:

- `backend = "cluster-command"`: current default, requires `cluster_id`, used
  by the Jupyter kernel and runner commands that need stateful Python.
- `backend = "sql-statement"`: SQL-only execution, requires `warehouse_id`,
  uses the Statement Execution API.
- `backend = "serverless-job"`: batch scripts or notebooks, uses Jobs API task
  submission and a separate file staging/output strategy. A first scoped
  feature could support only a single self-contained Python file.

Do not route individual Jupyter cells between these backends implicitly. A
single notebook session could observe inconsistent Python variables, temporary
views, working directories, library state, and output semantics.

## Acceptance Criteria Summary

- Available serverless API surfaces: Statement Execution API through SQL
  warehouses, Lakeflow Jobs/Jobs API for supported task types, Databricks UI
  serverless notebooks, and Spark Connect based APIs. Command Execution remains
  classic all-purpose only.
- Python single-file batch: feasible as a separate Jobs/Lakeflow serverless
  runner if the file is staged to a Databricks-accessible location and the
  implementation explicitly handles serverless environments, job output,
  timeout/cancel, cleanup, and documented serverless limitations.
- Notebook batch: feasible as a whole-notebook Jobs task, but not as
  cell-by-cell Jupyter kernel execution.
- Latency and cost: serverless reduces idle infrastructure management but does
  not guarantee lower interactive latency for every path; serverless workflows
  standard performance mode can have 4-6 minute startup latency, while classic
  clusters are slow when stopped but reusable once running.
- Notebook blockers: no public stateful serverless command context equivalent
  to Command Execution, no arbitrary Python execution through Statement
  Execution, batch lifecycle for Jobs, and storage/session/API limitations.
- Recommendation: complement, do not replace. Keep interactive kernel execution
  on classic all-purpose clusters, and open separate scoped work for SQL-only
  or batch serverless backends if desired.
