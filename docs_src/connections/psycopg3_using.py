from psycopg_pool import ConnectionPool

import pydapper

my_pool = ConnectionPool("postgresql://pydapper:pydapper@localhost/pydapper", min_size=1, max_size=10)

commands = pydapper.using(my_pool.getconn())
print(type(commands))
# <class 'pydapper.postgresql.psycopg3.Psycopg3Commands'>

print(type(commands.connection))
# <class 'psycopg.Connection'>

my_pool.putconn(commands.connection)
