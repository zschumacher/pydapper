# [MySQL](https://www.mysql.com/)
Supported drivers:

| dbapi                                                                    | default    | driver        | connection class                                   |
|--------------------------------------------------------------------------|------------|---------------|----------------------------------------------------|
| [mysql-connector-python](https://dev.mysql.com/doc/connector-python/en/) | :thumbsup: | `mysql+mysql` | `mysql.connector.connection_cext.CMySQLConnection` |

## mysql-connector-python
`mysql-connector-python` is the default dbapi driver for MySQL in *pydapper*.  It is actually registered as `mysql`
because that is the name of the actual package that is installed.

!!! note
    Because of the built-in behavior of `mysql-connector-python`, it is currently required to run `cursor.fetchall()`
    in the `query_first` implementation in order to flush the result set from the server.
    When using `query_first` with MySQL, it is advisable to use `LIMIT 1` in your query to prevent downloading
    unneeded rows.

    `query_single` reads only enough rows to detect that more than one row exists. If `mysql-connector-python`
    cannot discard the unread rows with its driver-level reset behavior, pydapper drains the remaining rows before
    raising `MoreThanOneResultException` so the connection remains usable. Use `LIMIT 2` with `query_single` to cap
    the cleanup cost for queries that may return many rows.

### Installation
=== "pip"
    ```console
    pip install pydapper[mysql-connector-python]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E mysql-connector-python
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"mysql+mysql://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "mysql+mysql://myuser:mypassword@localhost:3306/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "mysql://myuser:mypassword@localhost:3306/mydb"
    ```

!!! note
    Databases and schemas are synonymous in MySQL.

### Example - `connect`
The connection's context manager **only closes the connection on exit — it never commits**, so handle commits
yourself (see the example, and [Transactions](#mysql-transactions) below).
```python
{!docs/../docs_src/connections/mysql_connector_python_connect.py!}
```

### Example - `using`
Use *pydapper* with a `mysql-connector-python` connection pool.
```python
{!docs/../docs_src/connections/mysql_connector_python_using.py!}
```

### Transactions {#mysql-transactions}

`mysql-connector-python` connects with `autocommit=False`, so no DML is durable until you commit. Exiting
`with pydapper.connect(...)` delegates to the driver's context manager, which **only closes the connection —
uncommitted DML is discarded by the server**. Commit explicitly (`commands.commit()`) or scope the work in a
[`transaction()`](../transactions.md) block, which commits on clean exit; alternatively pass
`autocommit=True` to `connect()` to make every statement durable immediately.

One server-side caveat: **MySQL implicitly commits DDL statements** (`CREATE TABLE`, `ALTER`, `DROP`, … —
`CREATE`/`DROP TEMPORARY TABLE` are the documented exception), and that implicit commit also commits any
uncommitted DML issued earlier on the same connection — a rollback after DDL cannot undo work the DDL already
committed.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.
