# [Oracle](https://www.oracle.com/database/)
Supported drivers:

| dbapi                                                                   | default      | driver             | connection class       |
|-------------------------------------------------------------------------|--------------|--------------------|------------------------|
| [cx_Oracle](https://cx-oracle.readthedocs.io/en/latest/)                | :thumbsup:   | `oracle+cx_Oracle` | `cx_Oracle.Connection` |
| [oracledb](https://python-oracledb.readthedocs.io/en/latest/index.html) | :thumbsdown: | `oracle+oracledb`  | `oracledb.Connection`  |

## cx_Oracle
`cx_Oracle` is the default dbapi driver for Oracle in *pydapper*.

### Installation
=== "pip"

    ```console
    pip install pydapper[cx_Oracle]
    ```

=== "poetry"

    ```console
    poetry add pydapper -E cx_Oracle
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"oracle+cx_Oracle://{user}:{password}@{host}:{port}/{servicename}"
    ```

=== "Example"
    ```python
    dsn = "oracle+cx_Oracle://myuser:mypassword:1521@localhost/myservicename"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "oracle://myuser:mypassword:1521@localhost/myservicename"
    ```

!!! note
    You connect to `cx_Oracle` in *pydapper* using [service names](https://docs.oracle.com/cd/B19306_01/server.102/b14237/initparams188.htm#REFRN10194)

### Example - `connect`
Please see the 
[cx_Oracle docs](https://cx-oracle.readthedocs.io/en/latest/user_guide/connection_handling.html#closing-connections) 
for a full description of context manager behavior.

```python
{!docs/../docs_src/connections/cx_Oracle_connect.py!}
```

### Example - `using`
Use *pydapper* with a `cx_Oracle` connection pool.
```python
{!docs/../docs_src/connections/cx_Oracle_using.py!}
```

## oracledb

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
