import asyncio
import os
import sys
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# 1. Cloud-Native Logging (Twelve-Factor: stdout only, no local /tmp files)
logging.basicConfig(
    stream=sys.stdout, 
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("d5_reconciliation_worker")

# 2. Native OS Environment Lookups (No .env files allowed)
class ConfigurationError(Exception):
    pass

def get_env_var(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ConfigurationError(f"Missing mandatory environment variable: {var_name}")
    return value

# 3. Database Connection Pooling (Matches A2 constraints)
# pool_size=10, max_overflow=20 prevents session starvation
engine = create_async_engine(
    get_env_var("DATABASE_URL"), 
    pool_size=10, 
    max_overflow=20
)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Stub for Downstream Router API
async def execute_trade_downstream(payload: dict, idempotency_key: str):
    """
    Simulates calling the Multi-Asset Order Router / Exchange.
    Returns a tuple of (HTTP_STATUS_CODE, RESPONSE_DATA)
    """
    # In reality, this would be an aiohttp/httpx call with the X-Idempotency-Key header
    return 503, {"error": "Transient service unavailable"} 

async def process_trade_by_id(trade_id: int):
    """
    Processes a single RECONCILING trade within its own transaction scope.
    Implements 1s/2s/4s bounded retries and handles Vetoes safely.
    """
    async with SessionLocal() as session:
        # Step 1: Atomic Row Lock (Prevents duplicate execution across multiple workers)
        query = text("""
            SELECT id, client_idempotency_key, payload 
            FROM clax_trade_ledger 
            WHERE id = :id AND status = 'RECONCILING' 
            FOR UPDATE SKIP LOCKED
        """)
        result = await session.execute(query, {"id": trade_id})
        row = result.fetchone()
        
        if not row:
            # Another worker instance may have grabbed this, or it was manually resolved
            return

        idempotency_key = row.client_idempotency_key
        payload = row.payload
        logger.info(f"Locked trade {trade_id}. Attempting reconciliation using original key {idempotency_key}")
        
        # Step 2: Bounded Retry Logic (Acceptance Criteria: 3x, 1s/2s/4s)
        delays = [1, 2, 4]
        for attempt, delay in enumerate(delays, 1):
            try:
                # Acceptance Criteria: Same idempotency key reused
                status_code, response = await execute_trade_downstream(payload, idempotency_key)
                
                if status_code == 200:
                    logger.info(f"Trade {trade_id} execution SUCCESS on attempt {attempt}")
                    await session.execute(
                        text("UPDATE clax_trade_ledger SET status = 'SUCCESS' WHERE id = :id"),
                        {"id": trade_id}
                    )
                    await session.commit()
                    return
                    
                elif status_code in (403, 422):
                    # Acceptance Criteria: Vetoes (422/403) NOT retried
                    logger.warning(f"Trade {trade_id} hit compliance VETO ({status_code}). Aborting retries.")
                    await session.execute(
                        text("UPDATE clax_trade_ledger SET status = 'VETOED' WHERE id = :id"),
                        {"id": trade_id}
                    )
                    await session.commit()
                    return
                    
                else:
                    logger.warning(f"Transient error for trade {trade_id} (Status {status_code}) on attempt {attempt}. Retrying in {delay}s...")
                    
            except Exception as e:
                logger.error(f"Exception during trade {trade_id} execution: {e}")
                # We do NOT rollback here if it's just a network exception from execute_trade_downstream,
                # because we want to maintain the FOR UPDATE lock across retries.
                # However, if it's a DB error, the transaction is invalid.
                
            if attempt < len(delays):
                await asyncio.sleep(delay)
                
        # Step 3: Terminal Failure if all retries are exhausted
        try:
            logger.error(f"Trade {trade_id} exhausted all 3 bounded retries. Marking FAILED.")
            await session.execute(
                text("UPDATE clax_trade_ledger SET status = 'FAILED' WHERE id = :id"),
                {"id": trade_id}
            )
            await session.commit()
        except Exception as e:
            logger.error(f"Exception updating terminal failure for trade {trade_id}: {e}")
            await session.rollback()

async def worker_loop():
    """
    Main background loop. Scans every 60s for RECONCILING rows.
    """
    logger.info("Starting D5 Background Reconciliation Worker (60s loop)...")
    
    while True:
        try:
            async with SessionLocal() as session:
                # Lightweight fetch of candidate IDs. 
                # Explicitly ignores SUCCESS, FAILED, and VETOED (Compliance)
                result = await session.execute(text("""
                    SELECT id FROM clax_trade_ledger WHERE status = 'RECONCILING'
                """))
                candidate_ids = [row.id for row in result.fetchall()]
                
            if candidate_ids:
                logger.info(f"Found {len(candidate_ids)} RECONCILING trades. Spawning async tasks...")
                # Process concurrently, each securing its own FOR UPDATE SKIP LOCKED row lock
                tasks = [process_trade_by_id(tid) for tid in candidate_ids]
                await asyncio.gather(*tasks)
            else:
                logger.debug("No RECONCILING trades found. Network is stable.")
                
        except Exception as e:
            logger.error(f"Error in main worker scan loop: {e}")
        
        # Acceptance Criteria: Worker scans every 60s
        await asyncio.sleep(60)

if __name__ == "__main__":
    # Ensure this runs as an isolated, stateless background script
    asyncio.run(worker_loop())