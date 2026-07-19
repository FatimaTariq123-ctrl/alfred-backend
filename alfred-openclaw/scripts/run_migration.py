import os
import psycopg2

def main():
    conn_str = os.environ.get('NEON_DATABASE_URL')
    try:
        conn = psycopg2.connect(conn_str)
        conn.autocommit = True
        with conn.cursor() as cur:
            with open('/home/vboxuser/.openclaw/workspace/db_migrations/001_up.sql', 'r') as f:
                sql = f.read()
            cur.execute(sql)
        print("Migration executed successfully!")
    except Exception as err:
        print("Migration failed:", err)
    finally:
        if 'conn' in locals() and conn is not None:
            conn.close()

if __name__ == '__main__':
    main()
