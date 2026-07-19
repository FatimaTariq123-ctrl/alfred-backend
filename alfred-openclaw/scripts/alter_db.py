import os
import psycopg2

def main():
    conn_str = os.environ.get('NEON_DATABASE_URL')
    try:
        conn = psycopg2.connect(conn_str)
        conn.autocommit = True
        print("Connected to the live database.")
        with conn.cursor() as cur:
            sql = """
                ALTER TABLE clax_conditional_orders 
                ADD COLUMN IF NOT EXISTS trigger_condition VARCHAR(255),
                ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'PENDING',
                ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMP WITH TIME ZONE;
            """
            cur.execute(sql)
            print("Successfully added 'trigger_condition', 'status', and 'triggered_at' columns to clax_conditional_orders!")

            verify_sql = """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'clax_conditional_orders' 
                AND column_name IN ('trigger_condition', 'status', 'triggered_at');
            """
            cur.execute(verify_sql)
            rows = cur.fetchall()
            print("Verified Columns in DB:")
            print("column_name\tdata_type")
            for row in rows:
                print(f"{row[0]}\t{row[1]}")

    except Exception as err:
        print("Failed to alter table:", err)
    finally:
        if 'conn' in locals() and conn is not None:
            conn.close()

if __name__ == '__main__':
    main()
