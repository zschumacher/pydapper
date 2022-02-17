import datetime

from pydapper import connect

with connect() as commands:
    rowcount = commands.execute(
        "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
        param=[
            {"description": "An insert example", "due_date": datetime.date.today(), "owner_id": 1},
            {"description": "With multiple inserts!", "due_date": datetime.date.today(), "owner_id": 1},
        ],
    )

print(rowcount)
# 2
