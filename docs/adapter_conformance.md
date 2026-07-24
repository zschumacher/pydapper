# Adapter conformance

`pydapper.testing.adapter_conformance` is a reusable, typed conformance suite for adapter command classes. It
ships inside the installed `pydapper` distribution, so first-party and third-party adapter authors run the same
contract without copying tests out of the pydapper repository. The helper uses only the Python standard library
and pydapper core: it does not require pytest or any other test framework, it never imports an optional database
driver, and importing it starts no service, container, or emulator. It is not exported from the `pydapper`
package root; import it explicitly:

```python
from pydapper.testing.adapter_conformance import run_core_sync
```

## Mandatory profiles: `core-sync` and `core-async`

`core-sync` and `core-async` are the stable identifiers of the two mandatory profiles.

* Every registration that provides a **sync** command class promises `core-sync`.
* Every registration that provides an **async** command class promises `core-async`.

The two profiles are independent. An adapter registered for both modes must pass both; passing sync conformance
says nothing about async conformance, and a sync-only harness is never asked for async fields (or vice versa).
Mode support is represented by which command classes a registration supplies — these mandatory profiles are
**not** `AdapterCapability` flags.

Each profile covers registration and selection, the #541 cursor lifecycle (cleanup on success and active
failure, error precedence, truthy-exit non-suppression, plain and context-manager cursors, unbuffered
exhaustion and explicit `close()`/`aclose()`), parameter handling and execution, row mapping and `RawRow`
mappers, zero/one/many cardinality, scalar semantics (no row vs SQL `NULL` vs falsey values), command options,
preparation-hook ordering, and capability honesty. Cases are either **live** (they run through your real
database resources) or **instrumented** (they wrap your real concrete command class around framework-owned
recording and fault-injection connections, so cursor counts, call order, exception precedence, and
"fails before driver work" guarantees are observed directly rather than inferred from return values).

## Optional capability profiles

!!! warning "Provisional API — no capability profiles ship yet"
    `capability_profiles()` returns an **empty** catalog, and `ConformanceProfile`, `SyncCase`, and `AsyncCase`
    exist only so the first capability feature has somewhere to land. There is nothing for an adapter author to
    write against yet: no `AdapterCapability` member has a profile, and no adapter can usefully declare one. This
    part of the public API is **provisional and may change** when the first real capability profile is added; the
    mandatory `core-sync` / `core-async` surface described above is not. See
    [Extending the suite in future capability work](#extending-the-suite-in-future-capability-work) for what that
    first change must carry.

Optional behaviors are independent profiles keyed to `pydapper.AdapterCapability` members — there is no linear
"better adapter" tier, and no adapter is required to support any optional capability. The production catalog is
returned by `capability_profiles()` and is **currently empty**, because no optional capability is implemented
yet. The framework enforces honesty in both directions:

* A command class that declares a valid capability with no populated profile for its mode **fails** conformance
  (`capabilities.declared-profile-populated`). An unimplemented capability can never appear covered; zero-case
  profiles are rejected outright.
* A declaration that is not a `frozenset` of `AdapterCapability` members **fails** conformance
  (`capabilities.declaration-valid`).
* `supports()` must exactly match the class declaration (`capabilities.supports-matches-declaration`), and
  valid non-default `CommandOptions` for undeclared capabilities must raise `UnsupportedFeatureError` **before
  cursor acquisition or driver work** (`options.unsupported-raises`, `options.unsupported-before-driver-work`).

Native database support alone is never enough to declare a capability: a capability describes behavior the
command class actually implements, tests through its conformance profile, and documents. Until then, the
feature must fail loudly rather than silently execute as if supported.

## The harness API

A harness supplies factories, isolation, and narrow dialect knobs. It never owns assertions: every behavioral
check belongs to the framework runner, and harness- or adapter-provided code has no API to declare a case
passed.

Sync adapters subclass `SyncAdapterHarness`; async adapters subclass `AsyncAdapterHarness`.

Every configuration field below may be **declared on the subclass or assigned per instance** — none of them is a
`ClassVar`, so assigning to `self` in `__init__` type checks without a `type: ignore`. That matters for the
common case of a value that does not exist until a fixture has run, such as a DSN that is only known once a test
container has started:

```python
class MyHarness(SyncAdapterHarness):
    adapter_name = "acmedb"
    command_class = AcmeDbCommands

    def __init__(self, container):
        self.connect_dsn = f"acmedb://{container.host}:{container.port}/conformance"
```

A field that is genuinely static (`table_name`, `column_case`, `strict_rowcounts`, …) is still clearest as a
class attribute; both forms are supported and mix freely on one harness.

| Field | Required | Meaning |
|---|---|---|
| `adapter_name` | yes | The registered adapter name (exact, case-sensitive). |
| `command_class` | yes | The declared concrete `Commands` / `CommandsAsync` subclass for the mode. |
| `connect_dsn` | yes | A DSN that safely reaches an isolated test database through `connect()` / `connect_async()`. |
| `create_commands()` | yes | Return a fresh command instance over a fresh connection with the canonical dataset freshly seeded. Called once per case. |
| `teardown_commands(commands)` | yes | Release everything `create_commands()` built. Runs after success and failure. |
| `connect_kwargs` | no | Extra kwargs for the `connect()` path (for example BigQuery's `client=`). |
| `table_name` | no | Name (optionally schema/dataset qualified) of the conformance table. Default `pydapper_conformance`. |
| `column_case` | no | `"lower"` (default) or `"upper"` for dialects that fold unquoted identifiers (Oracle). |
| `supports_empty_strings` | no | `False` only when the database cannot store `''` distinctly from NULL (Oracle); the empty-string dataset value then seeds as the documented fallback `"blank"`. |
| `strict_rowcounts` | no | `False` only when DML rowcounts are documented as unreliable (BigQuery emulator). Rowcount cases still run and must return an `int`; only exact equality is relaxed. |
| `sql_overrides` | no | Statement-id → SQL overrides for the narrow cases where portable SQL is insufficient (still pydapper `?name?` placeholders). |
| `recover_after_error(commands)` | no | Backend recovery needed after an intentionally failed command (default no-op). |
| `cursor_factory_style` | async only | `"awaitable"` (default: `connection.cursor()` returns an awaitable, the `CommandsAsync` base contract) or `"synchronous"` (the psycopg3-async shape: `cursor()` returns the cursor directly and the command class normalizes it). Instrumented cases use this to exercise your real `cursor()` override. |

The framework owns the canonical dataset and every query it runs. `CONFORMANCE_COLUMNS` is
`("id", "label", "score", "note")` and `seed_rows(supports_empty_strings)` returns the three canonical rows —
including a SQL `NULL` note, a falsey `0` score, and an empty-string label — that `create_commands()` must
seed. All query and DML statements are written in pydapper's portable `?name?` placeholder syntax, so they run
unchanged on every adapter; the harness owns only DDL, seeding, and connection construction.

Every value the framework itself binds as a parameter is non-`NULL`. Some drivers — BigQuery's DBAPI, for
example — derive a parameter's type from its Python value and reject an untyped `None`, so binding `NULL` is
not part of the mandatory core profiles. The canonical dataset still contains a real SQL `NULL` note and
`scalar.null-returns-none` still asserts that a stored `NULL` reads back as `None`; producing that `NULL` is
the harness's job, and a harness whose driver cannot bind `None` may seed it any way its dialect allows (the
BigQuery harness binds a sentinel and then clears it with a literal `UPDATE ... SET note = NULL`).

A harness that does not supply a field a case needs fails that case with a structured
`HarnessDefinitionError` carrying the profile id, the case id, and the missing field name — a missing harness
field never silently skips or weakens a core case. There is deliberately no "skip this core case" option;
driver limitations are expressed only through the narrow, documented knobs above.

### Where to seed: under the adapter or through it

`create_commands()` must return a freshly seeded dataset, and there are two reasonable ways to produce it. Both
are used in this repository, so it is worth choosing deliberately:

* **Driver-level (recommended default).** Insert the rows with the raw driver, underneath the adapter — the
  `connection.executemany(...)` in both examples below, and what pydapper's own sqlite3 harness does. Setup then
  shares no code path with the thing under test, so a broken seed cannot be confused with broken adapter
  behavior, and reading the harness tells you exactly what is in the table.
* **Through the adapter.** Insert the rows with `commands.execute(...)` and pydapper's portable `?name?`
  placeholders, as pydapper's service-backed harnesses do through the shared
  `tests/conformance_support.py::seed_through_adapter` helper. One seeding statement then works unchanged across
  every dialect, which is why harnesses for many backends share it; the cost is that setup runs through the
  adapter it is about to judge.

Prefer driver-level seeding unless you are maintaining harnesses for several dialects at once and want a single
portable seeding path. This is a readability and blast-radius preference, not a correctness one: failures inside
`create_commands()` are attributed to the harness either way (see below), so seeding through the adapter no
longer risks a broken seed being reported as adapter misbehavior.

## Harness setup failures are attributed to the harness

If the harness's own `create_commands()` raises — a connection factory that cannot connect, a `CREATE TABLE`
against the wrong dataset, a seeding statement the driver rejects — the resulting `CaseResult` is failed with
`harness_setup_failed=True` and a message that names `create_commands()` as the culprit, while `cause` remains
the original exception object. `ConformanceReport.harness_setup_failed` is `True` if any case in the run has it,
and `ConformanceFailureError`'s summary gains a `[HARNESS SETUP FAILED: n of m failure(s) …]` segment, so the
traceback CI prints already says the harness never got off the ground.

This exists because one broken setup call fails every case that needs a fixture: without attribution, a single
bad seeding statement reads as dozens of identical behavioral failures against a perfectly good adapter. A run
with `harness_setup_failed` set is not a verdict on the adapter — fix the harness and run again.

The boundaries are narrow and deliberate:

* Only the harness's own `create_commands()` call is wrapped, never the framework's validation or bookkeeping
  around it, and never the adapter behavior a case exercises afterwards. Genuine behavioral failures keep their
  existing shape and report `harness_setup_failed=False`.
* `KeyboardInterrupt`, `SystemExit`, and `asyncio.CancelledError` still propagate unconverted; cancellation and
  shutdown are never turned into case results.
* A harness that omits a required field or override is still a `HarnessDefinitionError` with its `missing_field`
  — a missing override is a definition error, not a setup failure, and reporting for it is unchanged.
* The internal exception type used to carry this across the runner boundary is private. Branch on the two
  structured attributes (`CaseResult.harness_setup_failed`, `ConformanceReport.harness_setup_failed`), not on an
  exception class and not on message text.

## Case isolation and cleanup

Every case gets a fresh command instance, connection, and dataset through `create_commands()`; case ordering
and earlier failures cannot make later cases pass. `teardown_commands()` runs after every case, on success and
on failure. If both a case and its teardown fail, the case failure is preserved and the teardown failure is
retained as structured secondary information on the result (`CaseResult.cleanup_error`); a teardown failure
after an otherwise passing case fails that case.

## Deterministic, structured results

`run_core_sync()` / `run_core_async()` return a `ConformanceReport` whose `results` follow the declared
profile/case order exactly, run after run. Each `CaseResult` carries the profile id, case id, pass/fail, a
human-readable message, the original `cause` exception when one exists, the `missing_field` for harness
validation failures, any `cleanup_error`, and `harness_setup_failed`. `report.raise_for_failures()` raises a
`ConformanceFailureError` that exposes the same structured failures — nothing requires parsing exception
prose.

### Two flags that make a run mean less than it looks

`report.passed` answers "did every case that ran pass?" and nothing more. Two separate booleans say whether the
run was a conformance run at all, and both are structured attributes so no caller has to read messages:

| Flag | `True` means | What it invalidates |
|---|---|---|
| `report.covers_full_inventory` | every planned case ran (the default; `False` only after a `case_ids` filter) | a passing run that covered a subset is not conformance |
| `report.harness_setup_failed` | at least one case failed inside the harness's own `create_commands()` | the failures describe your harness, not the adapter |

Anything that **claims conformance** — a CI gate, a published matrix row, a release note — must therefore assert
`report.passed and report.covers_full_inventory`. `raise_for_failures()` deliberately ignores completeness: it
is about failures only, so a filtered run that passes everything it ran raises nothing.

```python
report = run_core_sync(MyAdapterHarness())
assert report.passed and report.covers_full_inventory
```

## Running one adapter

```python
from pydapper.testing.adapter_conformance import run_core_sync

report = run_core_sync(MyAdapterHarness())
for failure in report.failures:
    print(failure.profile_id, failure.case_id, failure.message)
report.raise_for_failures()
```

`run_core_async` is a plain awaitable and is awaited inside your own event loop — the framework never calls
`asyncio.run()` itself:

```python
report = await run_core_async(MyAsyncAdapterHarness())
```

### Debugging one case with `case_ids`

Both runners accept an optional `case_ids` collection that narrows the run to the named cases. It exists purely
to shorten the debug loop: against a container-backed backend, a full profile costs minutes per iteration —
mostly the client's connection retry backoff — which is a miserable way to chase one failing case.

```python
report = run_core_sync(MyAdapterHarness(), case_ids=["rows.query-buffered", "scalar.null-returns-none"])
assert report.covers_full_inventory is False  # by construction: this is a debug run, not a conformance run
```

The rules are chosen so a filtered run can never be mistaken for a real one:

* **A filtered run is never a conformance result.** `covers_full_inventory` is `False` whenever a filter narrowed
  the run, and `ConformanceFailureError`'s summary gains a `[PARTIAL RUN: …]` segment. Naming every planned case
  is still full coverage, and `case_ids=None` (the default) runs the full inventory exactly as before.
* **Unknown ids fail loudly, before anything runs.** A typo raises `CaseSelectionError` — carrying `profile_id`,
  `requested_case_ids`, and `unknown_case_ids` — rather than quietly running fewer cases. An empty selection
  raises the same error with an empty `unknown_case_ids`, because "no cases ran and none failed" is not a pass.
* **A bare string is a `TypeError`.** `case_ids="rows.query-buffered"` would otherwise be a collection of
  characters; pass a list.
* Ids come from `core_sync_profile().sync_cases` / `core_async_profile().async_cases` (plus any
  declared-capability profile cases, which are planned before filtering and so can also be selected).
  Duplicates are de-duplicated, and results still follow declared case order, not the order you requested.

### Complete third-party sync example

This one computes `connect_dsn` per instance in `__init__` — the shape a harness needs when the DSN only exists
after a fixture has run — and seeds at the driver level.

```python
{!docs/../docs_src/adapter_conformance/sync_example.py!}
```
(*This script is complete, it should run "as is"*)

### Complete third-party async example

This one declares `connect_dsn` on the class instead, which is the simpler form when the value is known up
front. Both forms are supported.

```python
{!docs/../docs_src/adapter_conformance/async_example.py!}
```
(*This script is complete, it should run "as is"*)

## Reporting service-backed runs you could not execute

Service-free evidence (mock harnesses and instrumented concrete-class cases) and live service-backed evidence
are different things, and reports must keep them distinct. A live suite that was skipped, or merely collected,
is a test-run status — never a pass. When you cannot run a live suite, report:

* whether the optional database driver was installed;
* whether the service or emulator was reachable;
* whether credentials were required and available; and
* which service-free conformance cases cover the same shared behavior.

## First-party driver conformance matrix

One row per first-party command class. "Verification" describes what is actually executed where — service-free
coverage runs everywhere, live suites run only under their backend marker when their Docker/testcontainers
service or emulator is available.

| Adapter name | Command class | Mode | Declared capabilities | Conformance entry | Verification | Driver limits |
|---|---|---|---|---|---|---|
| `sqlite3` | `Sqlite3Commands` | sync | *(none)* | `tests/test_sqlite/test_conformance.py` | live, service-free (runs in the core and sqlite suites) | [SQLite](database_support/sqlite.md) |
| `psycopg2` | `Psycopg2Commands` | sync | *(none)* | `tests/test_postgresql/test_conformance.py` | service-free instrumented + mock coverage; live suite under the `postgresql` marker when Docker is available | [PostgreSQL](database_support/postgresql.md) |
| `psycopg` | `Psycopg3Commands` | sync | *(none)* | `tests/test_postgresql/test_conformance.py` | service-free instrumented + mock coverage; live suite under the `postgresql` marker when Docker is available | [PostgreSQL](database_support/postgresql.md) |
| `psycopg` | `Psycopg3CommandsAsync` | async | *(none)* | `tests/test_postgresql/test_conformance.py` | service-free instrumented + mock coverage (including its synchronous cursor-factory normalization); live suite under the `postgresql` marker when Docker is available | [PostgreSQL](database_support/postgresql.md) |
| `aiopg` | `AiopgCommands` | async | *(none)* | `tests/test_postgresql/test_conformance.py` | service-free instrumented + mock coverage; live suite under the `postgresql` marker when Docker is available | [PostgreSQL](database_support/postgresql.md); aiopg is autocommit-only and emulates `executemany` by looping `execute` |
| `mysql` | `MySqlConnectorPythonCommands` | sync | *(none)* | `tests/test_mysql/test_conformance.py` | service-free instrumented + mock coverage (including its `query_first` unread-result drain); live suite under the `mysql` marker when Docker is available | [MySQL](database_support/mysql.md); unread results must be drained before a cursor closes |
| `pymssql` | `PymssqlCommands` | sync | *(none)* | `tests/test_mssql/test_conformance.py` | service-free instrumented + mock coverage; live suite under the `mssql` marker when Docker is available | [Microsoft SQL Server](database_support/mssql.md) |
| `oracledb` | `OracledbCommands` | sync | *(none)* | `tests/test_oracle/test_conformance.py` | service-free instrumented + mock coverage; live suite under the `oracle` marker when Docker is available | [Oracle](database_support/oracle.md); unquoted identifiers fold to uppercase (`column_case="upper"`), and `''` is stored as NULL (`supports_empty_strings=False`) |
| `google` | `GoogleBigqueryClientCommands` | sync | *(none)* | `tests/test_bigquery/test_conformance.py` | service-free instrumented + mock coverage; live suite under the `bigquery` marker when the emulator is available | [Google BigQuery](database_support/bigquery.md); the emulator's DML rowcounts are unreliable (`strict_rowcounts=False`), and the DBAPI cannot bind an untyped `None`, so the harness seeds the canonical SQL `NULL` note through a sentinel and a literal `UPDATE` |

## Extending the suite in future capability work

Every PR that adds or changes an optional capability must, in the same change:

* update the `AdapterCapability` enum/declaration when necessary;
* add a real, reusable capability profile to the production catalog (zero-case profiles are rejected, so an
  empty placeholder cannot ship);
* test at least one supported and one unsupported adapter against the new profile;
* update the affected first-party capability declaration;
* update driver limitations and documentation, including the matrix above; and
* update the type tests when public typing changes.

This keeps `supports()`, the declarations, the profiles, and the documentation honest together: a capability is
declared only when its implementation, its profile, and its documentation all exist.
