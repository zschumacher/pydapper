from cx_Oracle import SessionPool

import pydapper

my_pool = SessionPool(user="pydapper", password="pydapper", dsn="localhost:1522/pydapper")


commands = pydapper.using(my_pool.acquire())
print(type(commands))
# <class 'pydapper.oracle.cx_Oracle.CxOracleCommands'>

print(type(commands.connection))
# <class 'cx_Oracle.Connection'>

my_pool.release(commands.connection)
