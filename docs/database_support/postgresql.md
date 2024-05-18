# [PostgreSQL](https://www.postgresql.org)
Supported drivers:

| dbapi                                               | default      | driver                | connection class                                     |
|-----------------------------------------------------|--------------|-----------------------|------------------------------------------------------|
| [psycopg2](https://www.psycopg.org/docs/usage.html) | :thumbsup:   | `postgresql+psycopg2` | `psycopg2.extensions.connection`                     |
| [psycopg3](https://www.psycopg.org/psycopg3/docs/)  | :thumbsdown: | `postgresql+psycopg`  | `psycopg.Connection` \| `psycopg.AsyncConnection`    |
| [aiopg](https://aiopg.readthedocs.io/en/stable/)    | :thumbsdown: | `postgresql+aiopg`    | `aiopg.connection.Connection`                        |

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
    dsn = "postgresql+psycopg2://myuser:mypassword:1521@localhost/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "postgresql://myuser:mypassword:1521@localhost/mydb"
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

## psycopg3

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
    dsn = "postgresql+psycopg://myuser:mypassword:1521@localhost/mydb"
    ```

### Example - `connect`
Please see the [psycopg docs](https://www.psycopg.org/psycopg3/docs/basic/usage.html#with-connection) for a full description of the
context manager behavior.  
```python
{!docs/../docs_src/connections/psycopg3_connect.py!}
```

### Example - `connect_async`
Please see the [psycopg docs](https://www.psycopg.org/psycopg3/docs/advanced/async.html#async-with) for a full description of the
context manager behavior.
```python
{!docs/../docs_src/connections/psycopg3_connect_async.py!}
```

</details>

### Example - `using`
Use *pydapper* with a `psycopg` connection pool. Package that handles [connection pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html#connection-pools) is distributed separately from the main package.

=== "pip"
    ```console
    pip install psycopg_pool
    ```

=== "poetry"
    ```console
    poetry add psycopg_pool
    ```

```python
{!docs/../docs_src/connections/psycopg3_using.py!}
```

### Example - `using_async`
Use *pydapper* with a `psycopg` [async connection pools]((https://www.psycopg.org/psycopg3/docs/api/pool.html#the-asyncconnectionpool-class)). 

```python
{!docs/../docs_src/connections/psycopg3_using_async.py!}
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
    dsn = f"postgresql+aiopg://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "postgresql+aiopg://myuser:mypassword:1521@localhost/mydb"
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
