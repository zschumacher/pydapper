# [Oracle](https://www.oracle.com/database/)
Supported drivers:

| dbapi                                                                   | default    | driver             | connection class       |
|-------------------------------------------------------------------------|------------|--------------------|------------------------|
| [oracledb](https://python-oracledb.readthedocs.io/en/latest/index.html) | :thumbsup: | `oracle+oracledb`  | `oracledb.Connection`  |


## oracledb
`oracledb` is the default dbapi driver for Oracle in *pydapper*.

### Installation
=== "pip"

    ```console
    pip install pydapper[oracledb]
    ```

=== "poetry"

    ```console
    poetry add pydapper -E oracledb
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"oracle+oracledb://{user}:{password}@{host}:{port}/{servicename}"
    ```

=== "Example"
    ```python
    dsn = "oracle+oracledb://myuser:mypassword:1521@localhost/myservicename"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "oracle://myuser:mypassword:1521@localhost/myservicename"
    ```

!!! note
    You connect to `oracledb` in *pydapper* using [service names](https://docs.oracle.com/cd/B19306_01/server.102/b14237/initparams188.htm#REFRN10194)

### Example - `connect`
Please see the 
[oracledb docs](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html#creating-a-standalone-connection) 
for a full description of context manager behavior.

```python
{!docs/../docs_src/connections/oracledb_connect.py!}
```

### Example - `using`
Use *pydapper* with a `oracledb` connection pool.

```python
{!docs/../docs_src/connections/oracledb_using.py!}
```
