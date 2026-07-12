import asyncio
from typing import Any

from pydapper import RawRow
from pydapper import connect_async


def to_summary(row: RawRow) -> dict[str, Any]:
    values = row.as_dict()
    return {
        "task_id": values["task_id"],
        "owner_name": row["owner_name"],
    }


query = """
select
    t.id as task_id,
    o.name as owner_name
from task t
join owner o on t.owner_id = o.id
limit 1
"""


async def main():
    async with connect_async() as commands:
        data = await commands.query_async(query, mapper=to_summary)

    print(data)
    # [{'task_id': 1, 'owner_name': 'Zach Schumacher'}]


asyncio.run(main())
