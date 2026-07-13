from pydapper import connect

with connect() as commands:
    rows = commands.query("select * from task", buffered=False)
    print(type(rows))
    # <class 'generator'>

    try:
        for row in rows:
            print(row)
            break
    finally:
        rows.close()
