import mariadb

import pydapper

conn_from_pool = mariadb.connector.connect(
    pool_name="pydapper", pool_size=5, port=3307, password="pydapper", user="root", autocommit=True
)

commands = pydapper.using(conn_from_pool)
print(type(commands))
# <class 'pydapper.mysql.mysql_connector_python.MySqlConnectorPythonCommands'>

print(type(commands.connection))
# <class 'mysql.connector.pooling.PooledMySQLConnection'>

conn_from_pool.close()  # doesn't actually close, but returns it to pool "pydapper"
