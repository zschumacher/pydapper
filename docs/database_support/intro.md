
This section of the documentation describes what databases pydapper supports and how pydapper manages 
(or allows you to manage) connections.

There are four core concepts to understand about each dbapi *pydapper* supports:

**The dbapi package name**
: The name of the dbapi package that *pydapper* supports.

**Default :thumbsup: / :thumbsdown:**
: Is the dbapi the default for the dbms?  the dbapi indicated as the default can be declared in the DSN as 
  either `dbms+dbapi` or simply `dbms`.

: For example, a DSN for psycopg2 (the PostsgreSQL default) can be declared as 
  `postgresql://user:pw@server:port/dbname` OR `postgresql+psycopg2://user:pw@server:port/dbname`

**Driver name**
: The name of the driver that should be included in the dsn passed to the `connect` method (see examples).

**Base connection class**
: The class path used by the built-in automatic-selection predicate. Ordinary subclasses are recognized through their
  class MRO; wrappers and proxies should use explicit `adapter=` selection (see examples).




## DSN format

Connections managed by *pydapper* use URL-style DSNs with this grammar:

```text
<database>[+<adapter>]://[<user>[:<password>]@][<host>][:<port>]/<target>[?<query>][#<fragment>]
```

The scheme must follow the RFC URL-scheme rules: it starts with an ASCII letter and then contains only ASCII letters,
digits, `+`, `-`, or `.`. A scheme has either one database component or one database and one adapter component. Empty
components, underscores, and additional `+` components are invalid.

A one-component scheme selects the database's default adapter:

| database     | default adapter |
|--------------|-----------------|
| `postgresql` | `psycopg2`      |
| `sqlite`     | `sqlite3`       |
| `mssql`      | `pymssql`       |
| `mysql`      | `mysql`         |
| `oracle`     | `oracledb`      |
| `bigquery`   | `google`        |

These default database names should be written exactly as shown. An explicit scheme such as
`postgresql+psycopg://...` uses the adapter component exactly as written. Adapter registration names are case-sensitive,
so the explicit adapter spelling must exactly match the registered name. Explicit third-party schemes are supported:
for example, `acme+acmedb://...` selects an adapter registered as `acmedb`, even though `acme` has no built-in default.
An unknown one-component scheme is invalid because *pydapper* cannot derive an adapter. See
[Adapter registration](../adapter_registration.md) for the registration and selection contract.

### Adapter loading

The first-party adapters above are installed as standard `pydapper.adapters` entry points and load lazily. A plain
`import pydapper` does not initialize any adapter, import any adapter command module, or import any optional database
driver. A default or explicit DSN loads only the one adapter it selects, and explicit `adapter=` selection likewise
loads only that adapter and bypasses connection predicates. Automatic `using()` / `using_async()` selection (no
`adapter=`) may load every installed adapter provider, because it must evaluate all of their connection predicates to
pick exactly one match. Third-party adapter packages participate through the same entry-point group; see
[Adapter registration](../adapter_registration.md) for the packaging contract, precedence rules, and failure behavior.

Place the port after the host, not in the user information:

```text
postgresql+psycopg://myuser:mypassword@localhost:5432/mydb
```

Bracket IPv6 hosts so their colons cannot be confused with the port separator:

```text
postgresql://myuser:mypassword@[2001:db8::1]:5432/mydb
```

### Percent encoding

URL delimiters are recognized before components are percent-decoded. Percent-encode reserved characters when they are
data: for example, use `%40` for `@`, `%3A` for `:`, `%2F` for `/`, and `%20` for a space in credentials or paths. A
literal colon after the first username/password separator remains part of the password, but encoding reserved characters
is often clearer. Usernames, passwords, hosts, and paths are decoded before adapters receive them. A plus sign in a path
or credential remains a plus sign; it is not decoded as a space.

Percent-encoding does not make authority delimiters valid hostname data. After decoding, network hosts must still be
valid hostnames, IPv4 addresses, or bracketed IPv6 literals; control characters and Unicode characters that normalize
to delimiters such as `/`, `:`, `?`, `#`, or `@` are rejected.

Queries use URL-query decoding rules. Keys and values are percent-decoded, `+` becomes a space, and `%2B` represents a
literal plus sign. A key seen once maps to a string, a repeated key maps to a list in encounter order, and a blank value
remains an empty string. Numeric-looking and boolean-looking values are not converted:

```text
?mode=read+only&tag=one&tag=two&empty=&code=001&enabled=true
```

produces:

```python
{
    "mode": "read only",
    "tag": ["one", "two"],
    "empty": "",
    "code": "001",
    "enabled": "true",
}
```

The parse result's `query` and `query_str` fields retain the original encoded substring without the leading `?`, while
`query_params` contains the decoded mapping.

### Credential safety

Parsed credentials are available to adapters, but the parse result's representation and parser-generated errors redact
them. The original DSN is still retained in the result's `dsn` field for equality and routing, so treat both the DSN and
parse result as sensitive values and do not log them directly.

## Connection Management
*pydapper* supports BYOC (bring your own connection) via the `using` entry point or will manage the connection
lifecyle for you using `connect`.

### `connect`
*connect* will manage the connection for you.  When instantiating connect using a context manager, *connect* will use
the context manager that is implemented on the dbapi you are using.

When no DSN argument is supplied, both *connect* and *connect_async* fall back to the `PYDAPPER_DSN` environment
variable. An explicit DSN always takes precedence. Explicit empty or malformed input raises an error and is not silently
replaced by the environment value.

Below is a generic example of using *pydapper* to connect to `sqlite`.

```python
import pydapper

with pydapper.connect() as commands:
   # do stuff
```

### `connect_async`
*connect_async* will manage an asynchronous connection for you when using a dsn of a supported async dbapi.  The api
is almost identical to that of the sync api.

```python
import pydapper
import asyncio

async def main():
    async with pydapper.connect_async() as commands:
        # do stuff

asyncio.run(main())
```

### `using`
You should use the `using` method when you want to use your own connection.  A use case
for this could be if you have a custom connection pool in your application and you don't want a framework
to get in the way of using it.  Another example is reuse of connection objects from a framework like Django ORM
or SQLAlchemy.

Without an explicit adapter name, `using` first loads every installed adapter provider (so all connection predicates
are available), then runs the sync adapter predicates and requires exactly one match. Native DB-API connection objects
and ordinary subclasses of the supported connection classes are recognized. Pass a registered adapter name with
`adapter=` to override automatic selection when needed; explicit selection loads only that adapter.

Below is a generic example using *pydapper* with a connection managed by `django`.

```python
from django.db import connection

import pydapper

dbapi_connection_object = connection.connection
commands = pydapper.using(dbapi_connection_object)
```

What's going on here?

* importing the connection object proxy from `django.db`
* grab the actual dbapi connection object, which is stored in the `connection` property of the Django
  connection proxy
* pass the dbapi connection object into `pydapper.using` and get a pydapper `Commands` instance back

To override automatic selection, select the adapter directly. Explicit selection bypasses all predicates:

```python
commands = pydapper.using(dbapi_connection_object, adapter="psycopg2")
```

### `using_async`
You should use the `using_async` method when you want to use your own asynchronous connection. The API is almost
identical to the sync API: it automatically selects exactly one registered async adapter, or accepts `adapter=` to
override automatic selection.

```python
import pydapper

some_pool = ConnectionPool()
conn = await some_pool.acquire()
commands = pydapper.using_async(conn)

# Explicit adapter selection also works for async connections.
commands = pydapper.using_async(conn, adapter="psycopg")
```
