import pydapper
from psycopg2.pool import SimpleConnectionPool


my_pool = SimpleConnectionPool(1, 10, "postgresql://pydapper:pydapper@localhost/pydapper")


commands = pydapper.using(my_pool.getconn())
print(type(commands))
# <class 'pydapper.postgresql.psycopg2.Psycopg2Commands'>

print(type(commands.connection))
# <class 'psycopg2.extensions.connection'>

my_pool.putconn(commands.connection)
