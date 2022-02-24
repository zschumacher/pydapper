import asyncio

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        data = await commands.query_async("select * from task", buffered=False)

        print(type(data))
        # <class 'async_generator'>

        async for row in data:
            print(row)

        # {'id': 1, 'description': 'Set up a test database', 'due_date': datetime.date(2021, 12, 31), 'owner_id': 1}
        # {'id': 2, 'description': 'Seed the test database', 'due_date': datetime.date(2021, 12, 31), 'owner_id': 1}
        # {'id': 3, 'description': 'Run the test suite', 'due_date': datetime.date(2022, 1, 1), 'owner_id': 1}


asyncio.run(main())
