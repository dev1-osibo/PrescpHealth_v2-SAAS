import asyncio
import asyncpg

async def get_tables():
    conn = await asyncpg.connect('postgresql://postgres:2026victory@localhost:5432/prescphealth_test')
    rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    print("=== TABLES ===")
    for r in rows:
        print(r['tablename'])
    rows2 = await conn.fetch("SELECT tablename, rowsecurity, forcerowsecurity FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    print("\n=== RLS STATUS ===")
    for r in rows2:
        print(f"{r['tablename']}: rls={r['rowsecurity']}, force={r['forcerowsecurity']}")
    await conn.close()

asyncio.run(get_tables())
