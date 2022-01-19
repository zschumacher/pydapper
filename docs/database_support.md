pydapper currently supports the below DBMS's and drivers (plan to add more in the future).  The dbapi indicated
as the default can be declared in the DSN as either `dbms+dbapi` or simply `dbms`.

For example, a DSN for psycopg2 (the postgresql default) can be declared as `postgresql://user:pw@myserver:5432/mydbname`
or `postgresql+psycopg2://user:pw@myserver:5432/mydbname`

[PostgreSQL](https://www.postgresql.org)

| dbapi                                               | default    | driver                |
|-----------------------------------------------------|------------|-----------------------|
| [psycopg2](https://www.psycopg.org/docs/usage.html) | :thumbsup: | `postgresql+psycopg2` |

[Microsoft SQL Server](https://www.microsoft.com/en-us/sql-server/sql-server-2019)

| dbapi                              | default    | driver                |
|------------------------------------|------------|-----------------------|
| [pymssql](https://www.pymssql.org) | :thumbsup: | `mssqlserver+pymssql` |

[SQLite](https://www.sqlite.org/index.html)

| dbapi                                                     | default    | driver             |
|-----------------------------------------------------------|------------|--------------------|
| [sqlite3](https://docs.python.org/3/library/sqlite3.html) | :thumbsup: | ``sqlite+sqlite3`` |