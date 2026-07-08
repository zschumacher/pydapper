from pydapper import RawRow
from pydapper import connect


def to_task_description(row: RawRow) -> str:
    return row["description"]


def to_owner_name(row: RawRow) -> str:
    return row["name"]


with connect() as commands:
    task_descriptions, owner_names = commands.query_multiple(
        ("select description from task limit 1", "select name from owner limit 1"),
        mapper=(to_task_description, to_owner_name),
    )

print(task_descriptions)
# ['Set up a test database']
print(owner_names)
# ['Zach Schumacher']
