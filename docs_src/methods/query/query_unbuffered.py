from pydapper import connect

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    data = commands.query("select * from task", buffered=False)
    print(type(data))
    # <class 'generator'>
