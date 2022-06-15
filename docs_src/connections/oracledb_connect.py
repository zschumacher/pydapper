import pydapper

with pydapper.connect("oracle+oracledb://pydapper:pydapper@localhost:1522/pydapper") as commands:
    print(type(commands))
    # <class 'pydapper.oracle.oracledb.OracledbCommands'>

    print(type(commands.connection))
    # <class 'oracledb.Connection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'oracledb.Cursor'>
