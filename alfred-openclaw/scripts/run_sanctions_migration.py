import os
import psycopg2

def main():
    conn_str = os.environ.get('NEON_DATABASE_URL')
    try:
        conn = psycopg2.connect(conn_str)
        conn.autocommit = True
        with conn.cursor() as cur:
            with open('/home/vboxuser/.openclaw/workspace/db_migrations/002_sanctions_up.sql', 'r') as f:
                sql = f.read()
            cur.execute(sql)
            print("Sanctions table migration executed successfully!")
            
            seed_sql = """
                INSERT INTO sanctions_blacklist (ticker, name, regulatory_body, listed_on) VALUES
                ('RU-SANC', 'Sanctioned Russian Entity', 'OFAC', '2022-02-24'),
                ('HK-ALERT', 'Unlicensed HK Broker', 'SFC', '2023-01-15')
                ON CONFLICT (ticker) DO NOTHING;
            """
            cur.execute(seed_sql)
            print("Seeded sanctions table.")
    except Exception as err:
        print("Migration failed:", err)
    finally:
        if 'conn' in locals() and conn is not None:
            conn.close()

if __name__ == '__main__':
    main()
