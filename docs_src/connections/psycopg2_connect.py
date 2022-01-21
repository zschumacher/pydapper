from pydapper import connect

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    print(type(commands))
    # <class 'pydapper.postgresql.psycopg2.Psycopg2Commands'>

    print(type(commands.connection))
    # <class 'psycopg2.extensions.connection'>

    with commands.cursor() as raw_cursor:
        print(type(raw_cursor))
        # <class 'psycopg2.extensions.cursor'>
