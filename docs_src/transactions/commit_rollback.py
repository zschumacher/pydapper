import datetime

from pydapper import connect

with connect() as commands:
    commands.execute(
        "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
        params={"description": "A rollback example", "due_date": datetime.date.today(), "owner_id": 1},
    )
    # discard the uncommitted insert
    commands.rollback()

    commands.execute(
        "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
        params={"description": "A commit example", "due_date": datetime.date.today(), "owner_id": 1},
    )
    # make the insert durable
    commands.commit()
