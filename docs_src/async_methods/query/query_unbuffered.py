import asyncio

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        rows = await commands.query_async("select * from task", buffered=False)

        print(type(rows))
        # <class 'async_generator'>

        try:
            async for row in rows:
                print(row)
                break
        finally:
            await rows.aclose()


asyncio.run(main())
