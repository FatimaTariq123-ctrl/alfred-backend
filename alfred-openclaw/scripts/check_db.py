import os
import psycopg2

def main():
    conn_str = os.environ.get('NEON_DATABASE_URL')
    try:
        conn = psycopg2.connect(conn_str)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('clax_trade_ledger', 'clax_conditional_orders', 'clax_compliance_worm_logs', 'sanctions_blacklist');
            """)
            rows = cur.fetchall()
            table_names = [row[0] for row in rows]
            print("Current Tables in DB:", table_names)
    except Exception as err:
        print(err)
    finally:
        if 'conn' in locals() and conn is not None:
            conn.close()

if __name__ == '__main__':
    main()
