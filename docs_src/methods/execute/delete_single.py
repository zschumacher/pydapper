from pydapper import connect

with connect() as commands:
    rowcount = commands.execute("delete from task where id = ?id?", params={"id": 1})

print(rowcount)
# 1
