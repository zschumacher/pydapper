from pydapper import connect

with connect() as commands:
    rowcount = commands.execute("delete from task where id = ?id?", params=[{"id": 2}, {"id": 3}])

print(rowcount)
# 2
