# [MySQL](https://www.mysql.com/)
Supported drivers:

| dbapi                                                                    | default    | driver        | connection class                                   |
|--------------------------------------------------------------------------|------------|---------------|----------------------------------------------------|
| [mysql-connector-python](https://dev.mysql.com/doc/connector-python/en/) | :thumbsup: | `mysql+mysql` | `mysql.connector.connection_cext.CMySQLConnection` |

## mysql-connector-python
`mysql-connector-python` is the default dbapi driver for MySQL in *pydapper*.  It is actually registered as `mysql`
because that is the name of the actual package that is installed.

!!! note
    Because of the built-in behavior of `mysql-connector-python`, it is currently required to run `cursor.fetchall()`
    in the `query_first` implementation in order to flush the result set from the server.
    When using `query_first` with MySQL, it is advisable to use `LIMIT 1` in your query to prevent downloading
    unneeded rows.

    `query_single` reads only enough rows to detect that more than one row exists. If `mysql-connector-python`
    cannot discard the unread rows with its driver-level reset behavior, pydapper drains the remaining rows before
    raising `MoreThanOneResultException` so the connection remains usable. Use `LIMIT 2` with `query_single` to cap
    the cleanup cost for queries that may return many rows.

### Installation
=== "pip"
    ```console
    pip install pydapper[mysql-connector-python]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E mysql-connector-python
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"mysql+mysql://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "mysql+mysql://myuser:mypassword@localhost:3306/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "mysql://myuser:mypassword@localhost:3306/mydb"
    ```

!!! note
    Databases and schemas are synonymous in MySQL.

### Example - `connect`
The connection's context manager **only closes the connection on exit — it never commits**, so handle commits
yourself (see the example, and [Transactions](#mysql-transactions) below).
```python
{!docs/../docs_src/connections/mysql_connector_python_connect.py!}
```

### Example - `using`
Use *pydapper* with a `mysql-connector-python` connection pool.
```python
{!docs/../docs_src/connections/mysql_connector_python_using.py!}
```

### Transactions {#mysql-transactions}

`mysql-connector-python` connects with `autocommit=False`, so no DML is durable until you commit. Exiting
`with pydapper.connect(...)` delegates to the driver's context manager, which **only closes the connection —
uncommitted DML is discarded by the server**. Commit explicitly (`commands.commit()`) or scope the work in a
[`transaction()`](../transactions.md) block, which commits on clean exit; alternatively pass
`autocommit=True` to `connect()` to make every statement durable immediately.

One server-side caveat: **MySQL implicitly commits DDL statements** (`CREATE TABLE`, `ALTER`, `DROP`, … —
`CREATE`/`DROP TEMPORARY TABLE` are the documented exception), and that implicit commit also commits any
uncommitted DML issued earlier on the same connection — a rollback after DDL cannot undo work the DDL already
committed.

See [Transactions](../transactions.md) and
[Context manager semantics](intro.md#context-manager-semantics) for the cross-driver picture.

### Multi-statement SQL

`mysql-connector-python` negotiates `CLIENT_MULTI_STATEMENTS` by default, which lets the server execute a whole
batch of statements from one `execute()` call. pydapper does not want that capability on the wire, so
**connections pydapper opens clear the flag at connect time** — `pydapper.connect("mysql://...")` passes
`client_flags` that unset `CLIENT_MULTI_STATEMENTS`. (There is no async MySQL adapter; `mysql` registers a
sync command class only.)

The flag is cleared even when you supply your own `client_flags`:

```python
from mysql.connector.constants import ClientFlag

# your FOUND_ROWS is kept; MULTI_STATEMENTS is cleared regardless
pydapper.connect(dsn, client_flags=[ClientFlag.FOUND_ROWS])
```

| Your `client_flags` | What pydapper sends |
|---|---|
| omitted, `None`, `0`, or `False` | `[-MULTI_STATEMENTS]` |
| a `list` or `tuple` | your entries, with `-MULTI_STATEMENTS` appended last |
| a `list` or `tuple` that is empty | `[-MULTI_STATEMENTS]` |
| a **positive** `int` with other bits set | the same `int` with only that bit masked off |
| exactly `MULTI_STATEMENTS` | `ValueError` |
| any other falsy value (`''`, `set()`, `{}`) | `ValueError` |
| a negative `int`, or any other truthy value | forwarded unchanged, so the driver raises its own error |

Because pydapper always passes `client_flags`, it wins over a `client_flags` set in a `my.cnf` read through
`option_files` — the driver applies an option-file value only when the key is absent from the connect arguments. If you
keep flags in an option file, pass them to `connect()` instead; pydapper preserves them and appends only the denial.

The two `ValueError` cases exist because the driver resolves this option as
`config["client_flags"] or ClientFlag.get_default()`, and that default **has `MULTI_STATEMENTS` set**. Anything
falsy therefore skips the driver's own validation and silently re-enables the flag, so pydapper refuses rather
than sending a value it knows will be ignored. If you asked for `MULTI_STATEMENTS` and nothing else, there is no
honest answer — pass other flags alongside it, or open the connection yourself and use `using()`.

Connect-time denial covers only connections pydapper opens. A connection you build yourself and hand to
[`using()`](#example-using) keeps whatever flags you negotiated — the
[one-statement-per-call guard](../methods/query.md#one-statement-per-call) still applies to commands run through
it, which is why both halves exist.
