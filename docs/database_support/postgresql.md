# [PostgreSQL](https://www.postgresql.org)
Supported drivers:

| dbapi                                               | default      | driver                | connection class                                   |
|-----------------------------------------------------|--------------|-----------------------|----------------------------------------------------|
| [psycopg2](https://www.psycopg.org/docs/usage.html) | :thumbsup:   | `postgresql+psycopg2` | `psycopg2.extensions.connection`                   |
| [psycopg3](https://www.psycopg.org/psycopg3/docs/)  | :thumbsdown: | `postgresql+psycopg`  | `psycopg.Connection` \| `psycopg2.ConnectionAsync` |
| [aiopg](https://aiopg.readthedocs.io/en/stable/)    | :thumbsdown: | `postgresql+aiopg`    | `aiopg.connection.Connection`                      |

## psycopg2
`psycopg2` is the default dbapi driver for PostgreSQL in *pydapper*.

### Installation
=== "pip"
    ```console
    pip install pydapper[psycopg2]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E psycopg2
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "postgresql+psycopg2://myuser:mypassword@localhost:5432/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "postgresql://myuser:mypassword@localhost:5432/mydb"
    ```

### Example - `connect`
Please see the [psycopg2 docs](https://www.psycopg.org/docs/usage.html#with-statement) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/psycopg2_connect.py!}
```

### Example - `using`
Use *pydapper* with a `psycopg2` connection pool.
```python
{!docs/../docs_src/connections/psycopg2_using.py!}
```

### Transactions {#psycopg2-transactions}

`psycopg2` connects with autocommit off. All of pydapper's transaction APIs (`commit()`, `rollback()`,
`transaction()`) are supported. Exiting `with pydapper.connect(...)` delegates to
[psycopg2's context manager](https://www.psycopg.org/docs/usage.html#with-statement): it **commits on clean
exit, rolls back on error, and never closes the connection** — close it explicitly:

```python
with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    commands.execute(insert_sql, params=task)
# the exit committed the insert, but the connection is still open
commands.connection.close()
```

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.

## psycopg3
`psycopg3` is special because the driver supports both sync and async apis.  Connecting with both is listed below,
but note that the difference will be getting an `CommandsAsync` object instead of a `Commands` object when connecting in
async mode.

### Installation
=== "pip"
    ```console
    pip install pydapper[psycopg]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E psycopg
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "postgresql+psycopg://myuser:mypassword@localhost:5432/mydb"
    ```

### Example - `connect`
Please see the [psycopg docs](https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html#with-connection) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/psycopg3_connect.py!}
```

### Example - `connect_async`
Please see the [psycopg docs](https://www.psycopg.org/psycopg3/docs/advanced/async.html#with-async-connections) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/psycopg3_connect_async.py!}
```

### `using`, `using_async` and connection pools
Use *pydapper* with a `psycopg` connection pool. The package that handles [connection pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html#connection-pools) is distributed 
separately from the `psycopg`, and is called `psycopg_pool`; it supports both sync and async connection pools.

#### `psycopg_pool` installation
=== "pip"
    ```console
    pip install psycopg_pool
    ```

=== "poetry"
    ```console
    poetry add psycopg_pool
    ```

#### Example `using`
```python
{!docs/../docs_src/connections/psycopg3_using.py!}
```

#### Example `using_async`
```python
{!docs/../docs_src/connections/psycopg3_using_async.py!}
```

### Transactions {#psycopg3-transactions}

`psycopg` connects with autocommit off, in both modes. All of pydapper's transaction APIs are supported —
sync `commit()`/`rollback()`/`transaction()` on `Commands`, and their unsuffixed coroutine/async-CM twins on
`CommandsAsync` (`await commands.commit()`, `async with commands.transaction():`). psycopg is the only
first-party async adapter that supports transactions.

Exiting `with pydapper.connect(...)` (or `async with pydapper.connect_async(...)`) delegates to
[psycopg's connection context manager](https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html#with-connection),
which behaves the same in both modes: it **rolls back on error, commits on clean exit, and then closes the
connection** (unless the connection belongs to a pool). Unlike `psycopg2`, there is nothing left to close
after the block.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.

## aiopg

### Installation
=== "pip"
    ```console
    pip install pydapper[aiopg]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E aiopg
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"postgresql+aiopg://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "postgresql+aiopg://myuser:mypassword@localhost:5432/mydb"
    ```

### Example - `connect_async`
Please see the [aiopg docs](https://aiopg.readthedocs.io/en/stable/) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/aiopg_connect.py!}
```

### Example - `using_async`
Use *pydapper* with a `aiopg` connection pool.
```python
{!docs/../docs_src/connections/aiopg_using.py!}
```

### Transactions {#aiopg-transactions}

`aiopg` **always runs in
[autocommit mode](https://aiopg.readthedocs.io/en/stable/core.html#aiopg.Connection.autocommit)** — it cannot
be disabled, and the client cannot change the isolation level (the server's default, normally
`READ COMMITTED`, applies). Every statement is durable the moment it
executes, and there is no connection-level transaction to manage:

* `AiopgCommands` does **not** declare `AdapterCapability.TRANSACTIONS`, so pydapper's `commit()`,
  `rollback()`, and `transaction()` raise `UnsupportedFeatureError` before the connection is touched.
* The driver's own connection-level `commit()`/`rollback()` raise `psycopg2.ProgrammingError` ("cannot be
  used in asynchronous mode").
* Exiting `async with pydapper.connect_async(...)` **closes** the connection and nothing else — in autocommit
  mode there is no pydapper-managed transaction for it to commit or roll back (a transaction you open
  yourself with an explicit `BEGIN` is simply discarded by that close).
* aiopg ships its own SQL-emitting `Transaction` helper (`BEGIN`/`COMMIT` through a cursor); pydapper does
  not use it. If you need real async transactions on PostgreSQL, use the `psycopg` driver
  ([above](#psycopg3-transactions)) instead.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.
