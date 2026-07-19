import psycopg2
from psycopg2 import pool, OperationalError
import json
import sys
import time
from dotenv import load_dotenv
import os

sys.path.append('/home/ummara/clax/shared')
from logger import Timer

load_dotenv('/home/ummara/clax/.env')

connection_pool = None

def get_pool():
    global connection_pool
    if connection_pool is None:
        connection_pool = pool.SimpleConnectionPool(
            1, 5,
            os.getenv("NEON_DATABASE_URL"),
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
    return connection_pool

def get_connection():
    global connection_pool
    retries = 3
    for attempt in range(retries):
        try:
            conn = get_pool().getconn()
            conn.cursor().execute("SELECT 1")
            return conn
        except OperationalError:
            connection_pool = None
            if attempt < retries - 1:
                time.sleep(0.5)
    raise Exception("Failed to get DB connection after 3 attempts")

def release_connection(conn):
    try:
        get_pool().putconn(conn)
    except Exception:
        pass

def create_table():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_investor_dna (
                profile_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id           TEXT NOT NULL UNIQUE,
                created_date      DATE DEFAULT CURRENT_DATE,
                last_updated      DATE DEFAULT CURRENT_DATE,
                reprofile_due     DATE DEFAULT CURRENT_DATE + INTERVAL '6 months',
                archetype         TEXT,
                full_profile_json JSONB,
                raw_answers       JSONB
            );
        """)
        conn.commit()
        cur.close()
        print("✅ Table created successfully.")
    finally:
        release_connection(conn)

def save_profile(profile: dict):
    with Timer("investor-dna", "neondb_save", {"user_id": profile["user_id"]}):
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_investor_dna 
                    (user_id, archetype, full_profile_json, raw_answers, last_updated)
                VALUES (%s, %s, %s, %s, CURRENT_DATE)
                ON CONFLICT (user_id) 
                DO UPDATE SET
                    archetype         = EXCLUDED.archetype,
                    full_profile_json = EXCLUDED.full_profile_json,
                    raw_answers       = EXCLUDED.raw_answers,
                    last_updated      = CURRENT_DATE;
            """, (
                profile["user_id"],
                profile["archetype"],
                json.dumps(profile),
                json.dumps(profile["raw_answers"])
            ))
            conn.commit()
            cur.close()
        finally:
            release_connection(conn)
    print(f"✅ Profile saved for user: {profile['user_id']}")

def get_profile(user_id: str) -> dict | None:
    with Timer("investor-dna", "neondb_fetch", {"user_id": user_id}):
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT full_profile_json FROM user_investor_dna
                WHERE user_id = %s;
            """, (user_id,))
            row = cur.fetchone()
            cur.close()
        finally:
            release_connection(conn)
    if row:
        return row[0]
    return None

if __name__ == "__main__":
    create_table()