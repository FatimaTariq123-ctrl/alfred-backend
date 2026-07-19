import os
import psycopg2

def main():
    conn_str = os.environ.get('NEON_DATABASE_URL')
    try:
        conn = psycopg2.connect(conn_str)
        conn.autocommit = True
        with conn.cursor() as cur:
            with open('/home/vboxuser/.openclaw/workspace/db_migrations/001_down.sql', 'r') as f:
                sql_down = f.read()
            cur.execute(sql_down)
            print("Rolled back A2 tables (ledger, conditional orders, worm logs).")

            cur.execute('DROP TABLE IF EXISTS sanctions_blacklist CASCADE;')
            print("Rolled back A3 tables (sanctions).")
    except Exception as err:
        print("Rollback failed:", err)
    finally:
        if 'conn' in locals() and conn is not None:
            conn.close()

if __name__ == '__main__':
    main()
