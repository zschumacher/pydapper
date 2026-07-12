import asyncio

from pydapper import RawRow
from pydapper import connect_async


def to_task_description(row: RawRow) -> str:
    return row["description"]


def to_owner_name(row: RawRow) -> str:
    return row["name"]


async def main():
    async with connect_async() as commands:
        task_descriptions, owner_names = await commands.query_multiple_async(
            ("select description from task limit 1", "select name from owner limit 1"),
            mapper=(to_task_description, to_owner_name),
        )

    print(task_descriptions)
    # ['Set up a test database']
    print(owner_names)
    # ['Zach Schumacher']


asyncio.run(main())
