from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum

router = APIRouter(tags=["Wallet"])

# Mock Authentication
from fastapi.security import APIKeyHeader
api_key_header = APIKeyHeader(name="Authorization", auto_error=True, description="Enter Mock Token (e.g. Bearer mock_token)")

def verify_token(api_key: str = Depends(api_key_header)):
    if not api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return api_key

class WalletTypeEnum(str, Enum):
    usd = "usd"
    crypto = "crypto"

class DepositRequest(BaseModel):
    wallet_type: str
    amount: str

class WithdrawRequest(BaseModel):
    wallet_type: str
    amount: str

class ExchangeRequest(BaseModel):
    from_wallet_type: str
    to_wallet_type: str
    amount: str

@router.get("/wallet", summary="Get Wallet Overview")
def get_wallet_overview(token: str = Depends(verify_token)):
    return {
        "success": True,
        "data": {
            "total_value": "150000.00",
            "usd_wallet_balance": "80000.00",
            "crypto_wallet_balance": "70000.00",
            "breakdown": [
                { "category": "stocks", "value": "42500.00", "change": "2500.00" },
                { "category": "crypto", "value": "70000.00", "change": "5200.00" },
                { "category": "currency_usd", "value": "27500.00", "change": None },
                { "category": "currency_hkd", "value": "10000.00", "change": "-20.00" }
            ]
        }
    }

@router.get("/wallet/{wallet_type}/positions", summary="Get Wallet Positions")
def get_wallet_positions(wallet_type: WalletTypeEnum, token: str = Depends(verify_token)):
    return {
        "success": True,
        "data": {
            "balance": "80000.00",
            "positions": [
                { "symbol": "NFLX", "name": "Netflix, Inc", "change_percent": "0.12", "change": "0.01" },
                { "symbol": "TSLA", "name": "Tesla, Inc", "change_percent": "-0.12", "change": "-0.01" }
            ]
        }
    }

@router.post("/wallet/deposit", summary="Deposit")
def deposit(request: DepositRequest, token: str = Depends(verify_token), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    return {
        "success": True,
        "data": { "wallet_type": request.wallet_type, "new_balance": "80500.00", "transaction_id": "wtx_3d81" }
    }

@router.post("/wallet/withdraw", summary="Withdraw")
def withdraw(request: WithdrawRequest, token: str = Depends(verify_token), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    return {
        "success": True,
        "data": { "wallet_type": request.wallet_type, "new_balance": "79500.00", "transaction_id": "wtx_44f2" }
    }

@router.post("/wallet/exchange", summary="Exchange Between Wallets")
def exchange(request: ExchangeRequest, token: str = Depends(verify_token), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    return {
        "success": True,
        "data": {
            "from_wallet_type": request.from_wallet_type, "from_new_balance": "79500.00",
            "to_wallet_type": request.to_wallet_type, "to_new_balance": "70500.00",
            "transaction_id": "wtx_5a12"
        }
    }

@router.get("/wallet/transactions", summary="Wallet Transaction History")
def get_transactions(wallet_type: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None, token: str = Depends(verify_token)):
    return {
        "success": True,
        "data": [
            { "id": "wtx_1", "type": "deposit", "amount": "500.00", "wallet_type": "usd", "date": "2026-08-07T14:00:00Z" }
        ],
        "meta": { "next_cursor": "cur_987" }
    }