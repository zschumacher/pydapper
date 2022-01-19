from pydapper import connect

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    rowcount = commands.execute("delete from task where id = ?id?", param=[{"id": 2}, {"id": 3}])

print(rowcount)
# 2
