import pydapper

with pydapper.connect("mssql://sa:pydapper!PYDAPPER@localhost:1434/pydapper") as commands:
    print(type(commands))
    # <class 'pydapper.mssql.pymssql.PymssqlCommands'>

    print(type(commands.connection))
    # <class 'pymssql._pymssql.Connection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'pymssql._pymssql.Cursor'>
