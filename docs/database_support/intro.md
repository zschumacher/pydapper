
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
: The class path of the connection class that must be passed or inherited from when passed into the `using` method 
  (see examples).




## Connection Management
*pydapper* supports BYOC (bring your own connection) via the `using` entry point or will manage the connection
lifecyle for you using `connect`.

### `connect`
*connect* will manage the connection for you.  When instantiating connect using a context manager, *connect* will use
the context manager that is implemented on the dbapi you are using.

Below is a generic example of using *pydapper* to connect to `sqlite`.

```python
import pydapper

with pydapper.connect("some.db") as commands:
   # do stuff
```
ç

### `using`
You should use the `using` method when you want to use your own connection.  A use case
for this could be if you have a custom connection pool in your application and you don't want a framework
to get in the way of using it.  Another example is reuse of connection objects from a framework like Django ORM
or SQLAlchemy.

In order to use this entry point, the connection object you are passing in must be an instance of or inherit from
one of the dbapi connection objects that *pydapper* supports.

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
