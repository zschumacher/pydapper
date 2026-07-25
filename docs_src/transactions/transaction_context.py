import datetime

from pydapper import connect

with connect() as commands:
    with commands.transaction():
        commands.execute(
            "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
            params={"description": "A transaction example", "due_date": datetime.date.today(), "owner_id": 1},
        )
        commands.execute(
            "update task set description = ?description? where id = ?id?",
            params={"id": 1, "description": "Updated in the same transaction"},
        )
    # the block exited cleanly, so both statements are committed together
