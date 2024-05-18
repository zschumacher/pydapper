import asyncio

from psycopg_pool import AsyncConnectionPool

import pydapper


async def main():
    async with AsyncConnectionPool(
        "postgresql://pydapper:pydapper@localhost/pydapper", min_size=1, max_size=10, open=False
    ) as pool:
        conn = await pool.getconn()
        async with pydapper.using_async(conn) as commands:
            print(type(commands))
            # <class 'pydapper.postgresql.psycopg3.Psycopg3CommandsAsync'>

            print(type(commands.connection))
            # <class 'psycopg.AsyncConnection'>

            pool.putconn(commands.connection)


asyncio.run(main())
