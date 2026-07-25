# Transactions

pydapper's synchronous command classes expose explicit transaction handling: `commit()`, `rollback()`, and a
`transaction()` context manager. Transactions are deliberately boring — pydapper never emits `BEGIN` for you,
never toggles autocommit itself, and delegates directly to the DBAPI connection.

All three methods are gated behind `AdapterCapability.TRANSACTIONS`. An adapter that does not declare the
capability raises `UnsupportedFeatureError` immediately, before the connection is touched:

```python
import pydapper

with pydapper.connect("sqlite://pydapper.db") as commands:
    commands.supports(pydapper.AdapterCapability.TRANSACTIONS)  # True
```

Every first-party sync adapter except BigQuery declares the capability — see the
[first-party adapter table](adapter_registration.md#first-party-adapters). BigQuery does not, because its DBAPI
has no connection-level transactions (`commit()` is a no-op and there is no `rollback()`). The async transaction
APIs are a separate upcoming feature; async command classes do not declare the capability yet.

!!! note "`with pydapper.connect(...)` delegates exit behavior to the driver"
    `Commands.__enter__`/`__exit__` delegate to the driver connection's own context manager. Some drivers'
    connection context managers commit on clean exit (for example `sqlite3` and `psycopg2`), so leaving the
    `with connect(...)` block can itself commit outstanding work. The transaction APIs below operate on the
    same single connection-level transaction that behavior applies to.

## `commit()` and `rollback()`

`commit()` and `rollback()` delegate to the driver connection's `commit()` / `rollback()`. Per the DBAPI
contract, a transaction starts implicitly with your first statement — there is no `begin()`.

```python
{!docs/../docs_src/transactions/commit_rollback.py!}
```
(*This script is complete, it should run "as is"*)

## `transaction()`

`transaction()` returns a context manager that commits on clean exit and rolls back on any exception
(including `KeyboardInterrupt`) before re-raising it:

```python
{!docs/../docs_src/transactions/transaction_context.py!}
```
(*This script is complete, it should run "as is"*)

The exact semantics:

* **Entering the block emits no SQL.** The DBAPI's implicit transaction start is the contract; work done before
  the block on the same connection belongs to the same connection-level transaction.
* **Clean exit commits.** If the commit itself fails, the error propagates unchanged and no rollback is
  attempted — connection state after a failed commit is driver-defined.
* **An exception rolls back and re-raises.** The original exception always wins: if the rollback also fails,
  the rollback failure is suppressed and the block's exception propagates.
* **Blocks cannot be nested on the same `Commands` instance.** Re-entry raises `RuntimeError`. The guard is
  per instance, not per connection: a second `Commands` object over the same connection (for example from a
  second `using()` call) shares the same single connection-level transaction, and a `transaction()` block on
  one instance is not protected against `commit()`/`rollback()`/`transaction()` calls made through another.
  Use one `Commands` instance per connection when working with transactions. Savepoint-based nesting may
  arrive later as a separate, adapter-gated feature.
* **Explicit `commit()` / `rollback()` inside a block is allowed.** They operate on the same single
  connection-level transaction: an inner `commit()` makes the work so far durable, and the block's exit commit
  covers the remainder.

## Driver notes

Transaction behavior is pinned for every declaring adapter by the
[`transactions` conformance profile](adapter_conformance.md#the-transactions-profile), and per-driver limits
are recorded in the driver-limits column of the
[first-party conformance matrix](adapter_conformance.md#first-party-driver-conformance-matrix). Driver-level
transaction defaults still apply beneath these APIs — for example `mysql-connector-python` connects with
`autocommit=False` (so no DML is durable until you commit, though MySQL still implicitly commits every DDL
statement), and `sqlite3`'s legacy `isolation_level` mode
opens implicit transactions for DML but not DDL, which means a rolled-back block can leave a `CREATE TABLE`
behind. Consult your driver's own documentation for its autocommit and isolation semantics.
