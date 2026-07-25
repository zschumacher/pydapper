import pydapper

# mysql-connector-python defaults to autocommit=False, so no DML is durable until you
# commit; alternatively pass autocommit=True to connect to commit each statement immediately
with pydapper.connect("mysql+mysql://root:pydapper@localhost:3307/pydapper") as commands:
    print(type(commands))
    # <class 'pydapper.mysql.mysql_connector_python.MySqlConnectorPythonCommands'>

    print(type(commands.connection))
    # <class 'mysql.connector.connection_cext.CMySQLConnection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'mysql.connector.cursor_cext.CMySQLCursor'>

    # commit any outstanding work all together at the end of the block
    commands.commit()
