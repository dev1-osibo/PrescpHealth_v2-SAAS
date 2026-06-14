import asyncio
import asyncpg

async def get_rls():
    conn = await asyncpg.connect('postgresql://postgres:2026victory@localhost:5432/prescphealth_test')
    rows = await conn.fetch("""
        SELECT tablename, rowsecurity
        FROM pg_tables 
        WHERE schemaname='public' 
        ORDER BY tablename
    """)
    print("=== RLS STATUS ===")
    for r in rows:
        print(f"{r['tablename']}: rls_enabled={r['rowsecurity']}")
    
    # Also check policies
    policies = await conn.fetch("""
        SELECT tablename, policyname, cmd, roles::text
        FROM pg_policies
        WHERE schemaname='public'
        ORDER BY tablename, policyname
    """)
    print("\n=== RLS POLICIES ===")
    for p in policies:
        print(f"{p['tablename']}: {p['policyname']} ({p['cmd']}) roles={p['roles']}")
    
    await conn.close()

asyncio.run(get_rls())
