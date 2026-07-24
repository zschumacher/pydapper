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
validation failures, and any `cleanup_error`. `report.raise_for_failures()` raises a
`ConformanceFailureError` that exposes the same structured failures — nothing requires parsing exception
prose.

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

### Complete third-party sync example

```python
{!docs/../docs_src/adapter_conformance/sync_example.py!}
```
(*This script is complete, it should run "as is"*)

### Complete third-party async example

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
