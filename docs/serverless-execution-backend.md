# Serverless Execution Backend Investigation

Research date: 2026-05-24.

## Recommendation

Do not replace the current classic all-purpose cluster backend with Databricks
serverless compute.

Serverless compute can complement this project for specific non-interactive
paths, but it is not a drop-in backend for the current Jupyter kernel contract.
The current kernel and runner rely on the Databricks Command Execution API,
which creates a stateful execution context on a configured `cluster_id` and then
executes sequential Python commands in that context. The Databricks SDK
documents that Command Execution supports running Databricks clusters and only
classic all-purpose clusters; serverless compute is not supported.

Recommended path:

1. Keep the default Jupyter kernel and current runner behavior on classic
   all-purpose clusters.
2. Consider a separate SQL-only backend using the Statement Execution API and a
   SQL warehouse ID.
3. Consider a separate batch backend for `run-py`, `run-db-py`, or `run-ipynb`
   using serverless Lakeflow Jobs, if file staging and output capture are
   redesigned for workspace files, Unity Catalog volumes, or Git-backed
   notebook tasks.
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

| Surface                             | Serverless fit                  | Useful for this project          | Main limitation                                                        |
| ----------------------------------- | ------------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| Command Execution API               | No                              | Current kernel and runner backend | Classic all-purpose clusters only.                                     |
| Statement Execution API             | Yes, through SQL warehouses     | SQL-only execution path          | SQL statements only; no Python state, magics, or synchronized files.    |
| Lakeflow Jobs / Jobs API            | Yes, for supported task types   | Batch script or notebook runs    | Job/task lifecycle, not low-latency per-cell execution.                |
| Serverless notebooks in Databricks UI | Yes                            | Evidence for interactive support | UI flow, not a public Command Execution equivalent.                    |
| Spark Connect / Databricks Connect style | Serverless uses Spark Connect APIs | Possible future separate mode | Python runs locally; only Spark operations execute remotely.            |

## API Findings

### Command Execution API

The Command Execution API is the only current API surface in this project that
matches stateful cell-by-cell Python execution. It creates an execution context
and runs commands inside that context. It is not a serverless API.

Source:
<https://databricks-sdk-py.readthedocs.io/en/latest/workspace/compute/command_execution.html>

### Statement Execution API

The Statement Execution API runs SQL statements on a SQL warehouse. It supports
synchronous, asynchronous, and hybrid polling behavior through `wait_timeout`
and `on_wait_timeout`. It can return inline JSON results for small result sets
or external links for larger result sets.

This is viable for a SQL-only companion backend when the user configures a
`warehouse_id`. It does not satisfy the existing Python kernel semantics.

Source:
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

Sources:
<https://docs.databricks.com/aws/en/jobs/run-serverless-jobs>
<https://docs.databricks.com/api/workspace/jobs/create>

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
supported. Any serverless batch backend would need a separate staging design.

## Notebook-Style Execution Blockers

- No serverless support in the Command Execution API.
- No documented public serverless API that creates a reusable Python execution
  context equivalent to `context_id`.
- SQL warehouses can execute SQL but cannot run arbitrary Python cells.
- Jobs can run notebooks and scripts but are batch runs, not per-cell Jupyter
  kernel execution.
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
  submission and a separate file staging/output strategy.

Do not route individual Jupyter cells between these backends implicitly. A
single notebook session could observe inconsistent Python variables, temporary
views, working directories, library state, and output semantics.

## Acceptance Criteria Summary

- Available serverless API surfaces: Statement Execution API through SQL
  warehouses, Lakeflow Jobs/Jobs API for supported task types, Databricks UI
  serverless notebooks, and Spark Connect based APIs. Command Execution remains
  classic all-purpose only.
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
