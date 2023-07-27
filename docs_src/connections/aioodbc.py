import asyncio

import aioodbc

import pydapper


async def main():
    async with aioodbc.create_pool("mssql+aioodbc://pydapper:pydapper@localhost/pydapper") as pool:
        conn = await pool.acquire()
        async with pydapper.using_async(conn) as commands:
            print(type(commands))
            # <class 'pydapper.odbc.aioodbc.AioodbcCommands'>

            print(type(commands.connection))
            # <class 'aioodbc.connection.Connection'>


asyncio.run(main())
