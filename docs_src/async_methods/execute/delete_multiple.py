import asyncio

import pydapper


async def main():
    async with pydapper.connect_async() as commands:
        rowcount = await commands.execute_async("delete from task where id = ?id?", param=[{"id": 2}, {"id": 3}])

    print(rowcount)
    # 2


asyncio.run(main())
