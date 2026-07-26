import pydapper

with pydapper.connect("sqlite://pydapper.db") as commands:
    print(type(commands))
    # <class 'pydapper.sqlite.sqlite3.Sqlite3Commands'>

    print(type(commands.connection))
    # <class 'sqlite3.Connection'>

    # sqlite3 cursors are not context managers; close explicitly if you use one directly
    # (cursors owned by pydapper command methods are cleaned up for you)
    raw_cursor = commands.cursor()
    print(type(raw_cursor))
    # <class 'sqlite3.Cursor'>
    raw_cursor.close()
