from pydapper import connect

with connect() as commands:
    rowcount = commands.execute(
        "update task set description = ?desc? where id = ?id?", param={"desc": "A single update!", "id": 1}
    )

print(rowcount)
# 1
