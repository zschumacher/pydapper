# [Microsoft SQL Server](https://www.microsoft.com/en-us/sql-server/sql-server-2019)
Supported drivers:

| dbapi                              | default    | driver          | connection class              |
|------------------------------------|------------|-----------------|-------------------------------|
| [pymssql](https://www.pymssql.org) | :thumbsup: | `mssql+pymssql` | `pymssql._pymssql.Connection` |

## pymssql
`pymssql` is the default dbapi driver for Microsoft SQL Server in *pydapper*.


### Installation
=== "pip"
    ```console
    pip install pydapper[pymssql]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E pymssql
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"mssql+pymssql://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "mssql+pymssql://myuser:mypassword@localhost:1433/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "mssql://myuser:mypassword@localhost:1433/mydb"
    ```


### Example - `connect`
!!! warning
    Exiting the `with` block **closes the connection and rolls back any uncommitted work** — commit explicitly
    or use a [`transaction()`](../transactions.md) block. See [Transactions](#pymssql-transactions) below.
```python
{!docs/../docs_src/connections/pymssql_connect.py!}
```

### Example - `using`
Use *pydapper* with a custom connection pool.
```python
{!docs/../docs_src/connections/pymssql_using.py!}
```

### Transactions {#pymssql-transactions}

A non-autocommit `pymssql` connection (the default) holds an **always-open `BEGIN TRAN`**: the driver issues
one when the connection opens and re-issues one after every `commit()` and `rollback()`, so the connection is
never outside a transaction. Exiting `with pydapper.connect(...)` delegates to pymssql's context manager,
which **only closes the connection — and `close()` implicitly rolls back all uncommitted work**. This is the
classic silent-data-loss trap:

```python
with pydapper.connect("mssql://user:password@localhost:1433/mydb") as commands:
    rows = commands.execute(insert_sql, params=task)
    assert rows == 1  # True — but nothing was committed
# exit closed the connection, which rolled the insert back
```

Fix it either way — commit explicitly before the block ends:

```python
with pydapper.connect("mssql://user:password@localhost:1433/mydb") as commands:
    commands.execute(insert_sql, params=task)
    commands.commit()  # durable
```

or scope the work in a [`transaction()`](../transactions.md) block, which commits on clean exit:

```python
with pydapper.connect("mssql://user:password@localhost:1433/mydb") as commands:
    with commands.transaction():
        commands.execute(insert_sql, params=task)
    # committed
```

Two more pymssql quirks worth knowing:

* `autocommit` is a **method**, not an attribute: `commands.connection.autocommit(True)`. Turning autocommit
  on **discards the currently open transaction via a `ROLLBACK`**, so switch modes before doing work, not
  after.
* You can also pass `autocommit=True` to `connect()`'s kwargs to make every statement durable immediately.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.
