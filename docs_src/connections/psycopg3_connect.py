import pydapper

with pydapper.connect("postgresql+psycopg://pydapper:pydapper@localhost/pydapper") as commands:
    print(type(commands))
    # <class 'pydapper.postgresql.psycopg3.Psycopg3Commands'>

    print(type(commands.connection))
    # <class 'psycopg.Connection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'psycopg.Cursor'>
