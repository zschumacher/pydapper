import asyncio

import aioodbc

import pydapper


async def main():
    async with aioodbc.create_pool(
        dsn="DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost,1433;DATABASE=pydapper;UID=sa;PWD=pydapper"
    ) as pool:
        conn = await pool.acquire()
        async with pydapper.using_async(conn) as commands:
            print(type(commands))
            # <class 'pydapper.odbc.aioodbc.AioodbcCommands'>

            print(type(commands.connection))
            # <class 'aioodbc.connection.Connection'>


asyncio.run(main())
