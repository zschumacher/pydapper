import datetime

from pydapper import connect

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    rowcount = commands.execute(
        "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
        param={"description": "An insert example", "due_date": datetime.date.today(), "owner_id": 1},
    )

print(rowcount)
# 1
