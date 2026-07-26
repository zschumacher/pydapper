# [SQLite](https://www.sqlite.org/index.html)
Supported drivers:

| dbapi                                                     | default    | driver           | connection class     |
|-----------------------------------------------------------|------------|------------------|----------------------|
| [sqlite3](https://docs.python.org/3/library/sqlite3.html) | :thumbsup: | `sqlite+sqlite3` | `sqlite3.Connection` |

## sqlite3
`sqlite3` is the default dbapi driver for SQLite in *pydapper*.

### Installation
`sqlite3` is part of the stdlib and thus does not require installing an extra.
=== "pip"
    ```console
    pip install pydapper
    ```

=== "poetry"
    ```console
    poetry add pydapper
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"sqlite+sqlite3:///{relative_or_absolute_path_to_db}"
    ```

=== "Example"
    ```python
    dsn = "sqlite+sqlite3://my.db"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "sqlite://my.db"
    ```

SQLite slash counts distinguish relative and absolute paths. The connection target below is the value available as
`database` / `dbname` and passed to `sqlite3.connect()`; the parse result's `path` remains the decoded URL path before
this convenience normalization.

| DSN                                      | SQLite connection target |
|------------------------------------------|--------------------------|
| `sqlite://relative.db`                   | `relative.db`            |
| `sqlite+sqlite3://relative.db`           | `relative.db`            |
| `sqlite:///relative/path.db`             | `relative/path.db`       |
| `sqlite:////absolute/path.db`             | `/absolute/path.db`      |
| `sqlite:///:memory:`                      | `:memory:`               |
| `sqlite://`                               | empty string             |

Paths are percent-decoded without treating plus signs as spaces. For example,
`sqlite:///data/my%20database%23one.db` connects to `data/my database#one.db`.


### Example - `connect`
See [Transactions](#sqlite3-transactions) below for what the connection's context manager does on exit.
```python
{!docs/../docs_src/connections/sqlite3_connect.py!}
```

### Example - `using`
Use *pydapper* with a custom connection pool.
```python
{!docs/../docs_src/connections/sqlite3_using.py!}
```

### Transactions {#sqlite3-transactions}

`sqlite3` connects in its legacy `isolation_level` mode by default: an implicit transaction opens before the
first DML statement, and **DDL issued while no transaction is open runs in autocommit** — so a rolled-back
[`transaction()`](../transactions.md) block can leave a `CREATE TABLE` behind while its inserts are rolled
back. (DDL issued *after* DML has already opened the implicit transaction participates in it and rolls back
with it.) All of pydapper's transaction APIs (`commit()`, `rollback()`, `transaction()`) are supported.

Exiting `with pydapper.connect(...)` delegates to
[`sqlite3.Connection`'s own context manager](https://docs.python.org/3/library/sqlite3.html#using-the-connection-as-a-context-manager):
it **commits on clean exit, rolls back on error, and never closes the connection** — close it explicitly when
you are done:

```python
with pydapper.connect("sqlite://my.db") as commands:
    commands.execute(insert_sql, params=task)
# the exit committed the insert, but the connection is still open
commands.connection.close()
```

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.
