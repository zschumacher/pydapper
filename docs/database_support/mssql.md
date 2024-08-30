# [Microsoft SQL Server](https://www.microsoft.com/en-us/sql-server/sql-server-2019)
Supported drivers:

| dbapi                                          | default      | driver          | connection class                |
| ---------------------------------------------- | ------------ | --------------- | ------------------------------- |
| [pymssql](https://www.pymssql.org)             | :thumbsup:   | `mssql+pymssql` | `pymssql._pymssql.Connection`   |
| [aioodbc](https://github.com/aio-libs/aioodbc) | :thumbsdown: | `mssql+aioodbc` | `aioodbc.connection.Connection` |

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
    dsn = "mssql+pymssql://myuser:mypassword:1433@localhost/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "mssql://myuser:mypassword:1433@localhost/mydb"
    ```


### Example - `connect`
Please see the [pymssql docs](https://www.pymssql.org/pymssql_examples.html#using-the-with-statement-context-managers) for
a full description of the context manager behavior.
```python
{!docs/../docs_src/connections/pymssql_connect.py!}
```

### Example - `using`
Use *pydapper* with a custom connection pool.
```python
{!docs/../docs_src/connections/pymssql_using.py!}
```

## aioodbc
`aioodbc` supports async methods for Microsoft SQL Server and other ODBC-compatible databases. 
It is based on [pyodbc](https://github.com/mkleehammer/pyodbc).

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
To use async with MSSQL you need to use `aioodbc` driver.
Please see the [pyodbc docs](https://github.com/mkleehammer/pyodbc/wiki) for a full description about connecting.
```python
{!docs/../docs_src/connections/aioodbc_mssql_connect.py!}
```

### Example - `using_async`
Use *pydapper* with a `aioodbc` connection pool.
```python
{!docs/../docs_src/connections/aioodbc_mssql_using.py!}
```
