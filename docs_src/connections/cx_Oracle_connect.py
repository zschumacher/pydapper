import pydapper

with pydapper.connect("oracle+cx_Oracle://pydapper:pydapper@localhost:1522/pydapper") as commands:
    print(type(commands))
    # <class 'pydapper.oracle.cx_Oracle.CxOracleCommands'>

    print(type(commands.connection))
    # <class 'cx_Oracle.Connection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'cx_Oracle.Cursor'>
