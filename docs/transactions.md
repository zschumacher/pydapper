pydapper's synchronous command classes expose explicit transaction handling: `commit()`, `rollback()`, and a
`transaction()` context manager. Transactions are deliberately boring — pydapper never hides an autocommit
behind your back, never emits `BEGIN` for you, and delegates directly to the DBAPI connection.

All three methods are gated behind `AdapterCapability.TRANSACTIONS`. An adapter that does not declare the
capability raises `UnsupportedFeatureError` immediately, before the connection is touched:

```python
import pydapper
from pydapper.exceptions import UnsupportedFeatureError

with pydapper.connect("sqlite://pydapper.db") as commands:
    commands.supports(pydapper.AdapterCapability.TRANSACTIONS)  # True
```

Every first-party sync adapter except BigQuery declares the capability — see the
[first-party adapter table](adapter_registration.md#first-party-adapters). BigQuery does not, because its DBAPI
has no connection-level transactions (`commit()` is a no-op and there is no `rollback()`). The async transaction
APIs are a separate upcoming feature; async command classes do not declare the capability yet.

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
* **Blocks cannot be nested.** Opening a `transaction()` block inside an active one raises `RuntimeError`.
  There is only one connection-level transaction; savepoint-based nesting may arrive later as a separate,
  adapter-gated feature.
* **Explicit `commit()` / `rollback()` inside a block is allowed.** They operate on the same single
  connection-level transaction: an inner `commit()` makes the work so far durable, and the block's exit commit
  covers the remainder.

## Driver notes

Transaction behavior is pinned for every declaring adapter by the
[`transactions` conformance profile](adapter_conformance.md#the-transactions-profile). Driver-specific
documentation of transaction defaults (for example MySQL's `autocommit` connect kwarg and SQLite's
`isolation_level` modes) lives with each driver's page under [Database Support](database_support/intro.md).
