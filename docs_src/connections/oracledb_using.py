from oracledb import create_pool

import pydapper

my_pool = create_pool(user="pydapper", password="pydapper", dsn="localhost:1522/pydapper")


commands = pydapper.using(my_pool.acquire())
print(type(commands))
# <class 'pydapper.oracle.oracledb.OracledbCommands'>

print(type(commands.connection))
# <class 'oracledb.Connection'>

my_pool.release(commands.connection)
