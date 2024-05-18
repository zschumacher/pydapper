from psycopg_pool import ConnectionPool

import pydapper

pool = ConnectionPool("postgresql://pydapper:pydapper@localhost/pydapper", min_size=1, max_size=10, open=True)

commands = pydapper.using(pool.getconn())
print(type(commands))
# <class 'pydapper.postgresql.psycopg3.Psycopg3Commands'>

print(type(commands.connection))
# <class 'psycopg.Connection'>

pool.putconn(commands.connection)
