# [SQLite](https://www.sqlite.org/index.html)
Supported drivers:

| dbapi                                                     | default    | driver           | connection class     |
| --------------------------------------------------------- | ---------- | ---------------- | -------------------- |
| [sqlite3](https://docs.python.org/3/library/sqlite3.html) | :thumbsup: | `sqlite+sqlite3` | `sqlite3.Connection` |

## sqlite3
`sqlite3` is the default dbapi driver for SQLite in *pydapper*.

### Instalation
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
    dsn = f"sqlite+sqlite3://{path_to_db}"
    ```

=== "Example"
    ```python
    dsn = "sqlite+sqlite3://my.db"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "sqlite://my.db"
    ```


### Example - `connect`
Please see the [sqlite3 docs](https://docs.python.org/3/library/sqlite3.html#using-the-connection-as-a-context-manager) for
a full description of the context manager behavior.
```python
{!docs/../docs_src/connections/sqlite3_connect.py!}
```

### Example - `using`
Use *pydapper* with a custom connection pool.
```python
{!docs/../docs_src/connections/sqlite3_using.py!}
```

## aioodbc
`aioodbc` supports async methods for ODBC-compatible databases. It is based on [pyodbc](https://github.com/mkleehammer/pyodbc).
You may need to install [SQLite3 ODBC Driver](http://www.ch-werner.de/sqliteodbc/).

### Installation
=== "pip"
    ```console
    pip install pydapper[aioodbc]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E aioodbc
    ```

### Example - `connect_async`
To use async with SQLite you can use `aioodbc` driver.
Please see the [pyodbc docs](https://github.com/mkleehammer/pyodbc/wiki) for a full description about connecting.
```python
{!docs/../docs_src/connections/aioodbc_sqlite_connect.py!}
```

### Example - `using_async`
Use *pydapper* with a `aioodbc` connection pool.
```python
{!docs/../docs_src/connections/aioodbc_sqlite_using.py!}
```
