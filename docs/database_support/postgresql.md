# [PostgreSQL](https://www.postgresql.org)
Supported drivers:

| dbapi                                               | default    | driver                | connection class                 |
|-----------------------------------------------------|------------|-----------------------|----------------------------------|
| [psycopg2](https://www.psycopg.org/docs/usage.html) | :thumbsup: | `postgresql+psycopg2` | `psycopg2.extensions.connection` |

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
    dsn = "postgresql+psycopg2://myuser:mypassword:1521@localhost/myservicename"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "postgresql://myuser:mypassword:1521@localhost/myservicename"
    ```

### Example - `connect`
Please see the [psycopg2 docs](https://www.psycopg.org/docs/usage.html#with-statement) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/psycopg2_connect.py!}
```

<details>
<summary>The `psycopg2` context manager does not close your connection...</summary>

You must close it explicitly after exiting the context block:
```python
with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    # do stuff

# connection is still open, lets close it
commands.connection.close()
```

</details>

### Example - `using`
Use *pydapper* with a `psycopg2` connection pool.
```python
{!docs/../docs_src/connections/psycopg2_using.py!}
```

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
    dsn = f"postgresql+aipog://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "postgresql+aipog://myuser:mypassword:1521@localhost/myservicename"
    ```

### Example - `connect_async`
Please see the [aiopg docs](https://aiopg.readthedocs.io/en/stable/) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/aiopg_connect.py!}
```

!!! note
    `aiopg` always runs in [autocommit mode](https://aiopg.readthedocs.io/en/stable/core.html#aiopg.Connection.autocommit).


### Example - `using_async`
Use *pydapper* with a `aiopg` connection pool.
```python
{!docs/../docs_src/connections/aiopg_using.py!}
```
