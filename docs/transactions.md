# Transactions

pydapper's command classes expose explicit transaction handling in both modes: `commit()`, `rollback()`, and a
`transaction()` context manager on `Commands`, and the same names on `CommandsAsync` — `commit()`/`rollback()`
as coroutines and `transaction()` as an async context manager. Transactions are deliberately boring — pydapper
never emits `BEGIN` for you, never toggles autocommit itself, and delegates directly to the DBAPI connection.

All three methods are gated behind `AdapterCapability.TRANSACTIONS`. An adapter that does not declare the
capability raises `UnsupportedFeatureError` before the connection is touched — at call time for
`transaction()`, and when the call is awaited for the async `commit()`/`rollback()` coroutines:

```python
import pydapper

with pydapper.connect("sqlite://pydapper.db") as commands:
    commands.supports(pydapper.AdapterCapability.TRANSACTIONS)  # True
```

Every first-party adapter declares the capability except two — see the
[first-party adapter table](adapter_registration.md#first-party-adapters):

* **BigQuery** — its DBAPI has no connection-level transactions (`commit()` is a no-op and there is no
  `rollback()`).
* **aiopg** — it always runs in autocommit mode, and its connection-level `commit()`/`rollback()` raise.

!!! note "`with pydapper.connect(...)` delegates exit behavior to the driver"
    `Commands.__enter__`/`__exit__` (and the `CommandsAsync` async equivalents) delegate to the driver
    connection's own context manager — see
    [Context manager semantics](database_support/intro.md#context-manager-semantics) — and the drivers fall
    into three families. Some **commit on clean exit**: `sqlite3` and `psycopg2` (neither closes), and
    `psycopg` (commits, then closes). Some **only close**: `mysql-connector-python` discards uncommitted DML,
    and `aiopg` closes too (everything was already durable — it is autocommit-only). Some **close with an
    implicit rollback**: `pymssql` and `oracledb` throw away uncommitted work on exit. BigQuery is its own
    case: its connection has no context manager at all, so exit performs no driver call whatsoever. The
    per-driver table below links to
    each driver's details. The transaction APIs on this page operate on the same single connection-level
    transaction those behaviors apply to.

## `commit()` and `rollback()`

`commit()` and `rollback()` delegate to the driver connection's `commit()` / `rollback()`. Per the DBAPI
contract, a transaction starts implicitly with your first statement — there is no `begin()`.

```python
{!docs/../docs_src/transactions/commit_rollback.py!}
```
(*This script is complete, it should run "as is"*)

On `CommandsAsync` they are coroutines with the same names — await them:

```python
{!docs/../docs_src/transactions/commit_rollback_async.py!}
```
(*This script is complete, it should run "as is"*)

## `transaction()`

`transaction()` returns a context manager that commits on clean exit and rolls back on any exception
(including `KeyboardInterrupt`) before re-raising it:

```python
{!docs/../docs_src/transactions/transaction_context.py!}
```
(*This script is complete, it should run "as is"*)

On `CommandsAsync`, use `async with`:

```python
{!docs/../docs_src/transactions/transaction_context_async.py!}
```
(*This script is complete, it should run "as is"*)

The exact semantics, identical in both modes:

* **Entering the block emits no SQL.** The DBAPI's implicit transaction start is the contract; work done before
  the block on the same connection belongs to the same connection-level transaction.
* **Clean exit commits.** If the commit itself fails, the error propagates unchanged and no rollback is
  attempted — connection state after a failed commit is driver-defined.
* **An exception rolls back and re-raises.** The block's exception is re-raised as the same object, and it wins
  over an ordinary rollback failure: an `Exception` raised by the rollback is suppressed (recorded at `DEBUG`).
  A rollback failure that is *not* an `Exception` — a `KeyboardInterrupt`, `SystemExit`, a task cancellation —
  is an interpreter-level request to stop, so that one propagates in place of the block's exception, which
  survives as its `__context__` (the same policy as command-owned cursor cleanup); losing a Ctrl-C raised
  inside the driver's rollback is worse than reporting it.
* **Blocks cannot be nested on the same command instance.** Re-entry raises `RuntimeError`, which rolls the
  outer block back like any other error, and the guard clears on exit so the next block on the same instance
  works normally. The guard is per `Commands`/`CommandsAsync` instance, not per connection: a second instance
  over the same connection (for example from a second `using()`/`using_async()` call) shares the same single
  connection-level transaction, and a `transaction()` block on one instance is not protected against
  `commit()`/`rollback()`/`transaction()` calls made through another. Use one command instance per connection
  when working with transactions. Savepoint-based nesting may arrive later as a separate, adapter-gated
  feature.
* **Explicit `commit()` / `rollback()` inside a block is allowed.** They operate on the same single
  connection-level transaction: an inner `commit()` makes the work so far durable, and the block's exit commit
  covers the remainder.

!!! note "Naming"
    The transaction methods are deliberately unsuffixed on `CommandsAsync` — the class itself is async-only, so
    an `_async` suffix would be redundant (`cursor()` and `supports()` are likewise unsuffixed). The execute
    and query command methods currently keep their historical `_async` suffixes, and `connect_async` keeps its
    suffix on purpose: it disambiguates mode at the package boundary, next to the sync `connect`.

## Driver notes

Transaction behavior is pinned for every declaring adapter in both modes by the
[`transactions` conformance profile](adapter_conformance.md#the-transactions-profile), and per-driver limits
are recorded in the driver-limits column of the
[first-party conformance matrix](adapter_conformance.md#first-party-driver-conformance-matrix). Driver-level
transaction defaults still apply beneath these APIs; each driver's page documents its own behavior in detail:

| Driver | Autocommit default | `with connect(...)` exit does | Details |
|---|---|---|---|
| `sqlite3` | off (legacy `isolation_level` — implicit transactions open on DML; DDL outside an open transaction is autocommitted) | commits on clean exit, rolls back on error; does **not** close | [SQLite](database_support/sqlite.md#sqlite3-transactions) |
| `psycopg2` | off | commits on clean exit, rolls back on error; does **not** close | [PostgreSQL](database_support/postgresql.md#psycopg2-transactions) |
| `psycopg` (sync + async) | off | commits on clean exit, rolls back on error, then **closes** | [PostgreSQL](database_support/postgresql.md#psycopg3-transactions) |
| `aiopg` | always on | closes; every statement was already durable | [PostgreSQL](database_support/postgresql.md#aiopg-transactions) |
| `mysql` | off | **closes only** — uncommitted DML is discarded; MySQL implicitly commits DDL (temporary tables excepted) | [MySQL](database_support/mysql.md#mysql-transactions) |
| `pymssql` | off (always-open `BEGIN TRAN`) | **closes only** — `close()` implicitly rolls back uncommitted work | [SQL Server](database_support/mssql.md#pymssql-transactions) |
| `oracledb` | off | **rolls back** uncommitted work, then closes; Oracle implicitly commits DDL | [Oracle](database_support/oracle.md#oracledb-transactions) |
| `google` (BigQuery) | effectively per-statement | nothing — the DBAPI connection has no context manager | [BigQuery](database_support/bigquery.md#bigquery-transactions) |
