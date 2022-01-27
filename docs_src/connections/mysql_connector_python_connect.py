from pydapper import connect

# NOTE: setting autocommit to True will cause the transaction to commit immediately
with connect("mysql+mysql-connector-python://root:pydapper@localhost:3307/pydapper", autocommit=True) as commands:
    print(type(commands))
    # <class 'pydapper.mysql.mysql_connector_python.MySqlConnectorPythonCommands'>

    print(type(commands.connection))
    # <class 'mysql.connector.connection_cext.CMySQLConnection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'mysql.connector.cursor_cext.CMySQLCursor'>

    # you could alternatively commit your transaction all together at the end of the block
    commands.connection.commit()
