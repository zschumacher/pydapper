import pydapper

with pydapper.connect("sqlite://pydapper.db") as commands:
    print(type(commands))
    # <class 'pydapper.sqlite.sqlite3.Sqlite3Commands'>

    print(type(commands.connection))
    # <class 'sqlite3.Connection'>

    # pydapper inherits from `sqlite3.Cursor` in order to supply a context manager
    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'pydapper.sqlite.sqlite3.Sqlite3Cursor'>
        print(raw_cursor.__class__.__bases__)
        # (<class 'sqlite3.Cursor'>,)
