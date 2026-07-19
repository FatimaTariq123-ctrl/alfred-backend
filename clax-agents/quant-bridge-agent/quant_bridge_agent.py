import requests
import json
from config import OPTIMAL_ENTRY_URL, TOP10_MONTHLY_PICKS_URL, PORTFOLIO_REBALANCE_URL, REQUEST_TIMEOUT

def call_optimal_entry(ticker: str) -> dict:
    """
    Calls the Optimal Entry Price ML FastAPI service.
    """
    payload = {"ticker": ticker}
    try:
        response = requests.post(OPTIMAL_ENTRY_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {
            "error": "Timeout",
            "detail": f"Request to Optimal Entry service at {OPTIMAL_ENTRY_URL} timed out after {REQUEST_TIMEOUT}s."
        }
    except requests.exceptions.ConnectionError:
        return {
            "error": "ConnectionError",
            "detail": f"Could not connect to Optimal Entry service at {OPTIMAL_ENTRY_URL}. Ensure the service is running."
        }
    except requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json()
        except Exception:
            err_detail = e.response.text
        return {
            "error": f"HTTPError {e.response.status_code}",
            "detail": err_detail
        }
    except Exception as e:
        return {
            "error": "UnexpectedError",
            "detail": str(e)
        }

def call_top10_monthly_picks(date: str = None) -> dict:
    """
    Calls the Top-10 Monthly Picks ML FastAPI service.
    """
    params = {}
    if date:
        params["date"] = date
    try:
        response = requests.get(TOP10_MONTHLY_PICKS_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {
            "error": "Timeout",
            "detail": f"Request to Top-10 Monthly Picks service at {TOP10_MONTHLY_PICKS_URL} timed out after {REQUEST_TIMEOUT}s."
        }
    except requests.exceptions.ConnectionError:
        return {
            "error": "ConnectionError",
            "detail": f"Could not connect to Top-10 Monthly Picks service at {TOP10_MONTHLY_PICKS_URL}. Ensure the service is running."
        }
    except requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json()
        except Exception:
            err_detail = e.response.text
        return {
            "error": f"HTTPError {e.response.status_code}",
            "detail": err_detail
        }
    except Exception as e:
        return {
            "error": "UnexpectedError",
            "detail": str(e)
        }

def call_rebalance_portfolio(payload: dict) -> dict:
    """
    Calls the Portfolio Rebalancing Agent ML FastAPI service.
    """
    try:
        response = requests.post(PORTFOLIO_REBALANCE_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {
            "error": "Timeout",
            "detail": f"Request to Portfolio Rebalancing service at {PORTFOLIO_REBALANCE_URL} timed out after {REQUEST_TIMEOUT}s."
        }
    except requests.exceptions.ConnectionError:
        return {
            "error": "ConnectionError",
            "detail": f"Could not connect to Portfolio Rebalancing service at {PORTFOLIO_REBALANCE_URL}. Ensure the service is running."
        }
    except requests.exceptions.HTTPError as e:
        try:
            err_detail = e.response.json()
        except Exception:
            err_detail = e.response.text
        return {
            "error": f"HTTPError {e.response.status_code}",
            "detail": err_detail
        }
    except Exception as e:
        return {
            "error": "UnexpectedError",
            "detail": str(e)
        }
