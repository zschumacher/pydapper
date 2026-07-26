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
    dsn = "oracle+oracledb://myuser:mypassword@localhost:1521/myservicename"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "oracle://myuser:mypassword@localhost:1521/myservicename"
    ```

!!! note
    You connect to `oracledb` in *pydapper* using [service names](https://docs.oracle.com/cd/B19306_01/server.102/b14237/initparams188.htm#REFRN10194)

### Example - `connect`
Exiting the `with` block **closes the connection and rolls back any uncommitted work** — see
[Transactions](#oracledb-transactions) below.

```python
{!docs/../docs_src/connections/oracledb_connect.py!}
```

### Example - `using`
Use *pydapper* with a `oracledb` connection pool.

```python
{!docs/../docs_src/connections/oracledb_using.py!}
```

### Transactions {#oracledb-transactions}

`oracledb` connects with autocommit off (`connection.autocommit` is a read-write property if you want
per-statement commits). Exiting `with pydapper.connect(...)` delegates to the
[driver's context manager](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html#closing-connections),
which **rolls back uncommitted work and closes the connection — it never commits**. Commit explicitly
(`commands.commit()`) or scope the work in a [`transaction()`](../transactions.md) block, which commits on
clean exit.

One server-side caveat: **Oracle implicitly commits DDL statements**, and that implicit commit also
commits any uncommitted DML issued earlier on the same connection.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.
