import asyncio
import datetime

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        async with commands.transaction():
            await commands.execute_async(
                "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
                params={"description": "A transaction example", "due_date": datetime.date.today(), "owner_id": 1},
            )
            await commands.execute_async(
                "update task set description = ?description? where id = ?id?",
                params={"id": 1, "description": "Updated in the same transaction"},
            )
        # the block exited cleanly, so both statements are committed together


asyncio.run(main())
