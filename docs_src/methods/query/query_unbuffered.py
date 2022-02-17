from pydapper import connect

with connect() as commands:
    data = commands.query("select * from task", buffered=False)
    print(type(data))
    # <class 'generator'>
