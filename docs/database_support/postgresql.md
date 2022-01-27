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
