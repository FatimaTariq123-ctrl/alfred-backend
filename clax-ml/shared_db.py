import os
import pandas as pd
from sqlalchemy import create_engine

def get_engine():
    db_url = os.environ.get("NEON_DATABASE_URL", "postgresql://admin:admin@localhost/paper_db")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(db_url, pool_size=5, max_overflow=10)

def save_to_db(df: pd.DataFrame, table_name: str):
    engine = get_engine()
    df.to_sql(table_name, engine, if_exists='replace', index=False)

def load_from_db(query: str, params: tuple = None) -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(query, engine, params=params)
