# [SQLite](https://www.sqlite.org/index.html)
Supported drivers:

| dbapi                                                     | default    | driver           | connection class     |
|-----------------------------------------------------------|------------|------------------|----------------------|
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
