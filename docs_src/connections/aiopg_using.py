import asyncio

import aiopg

import pydapper


async def main():
    async with aiopg.create_pool("postgresql://pydapper:pydapper@localhost/pydapper") as pool:
        conn = await pool.acquire()
        async with pydapper.using_async(conn) as commands:
            print(type(commands))
            # <class 'pydapper.postgresql.aiopg.AiopgCommands'>

            print(type(commands.connection))
            # <class 'aiopg.connection.Connection'>


asyncio.run(main())
