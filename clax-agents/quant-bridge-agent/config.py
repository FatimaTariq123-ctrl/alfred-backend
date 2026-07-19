import os
from dotenv import load_dotenv

# Set up project-relative path imports for the shared module and load env
current_dir = os.path.dirname(os.path.abspath(__file__))
clax_agents_dir = os.path.dirname(current_dir)
dotenv_path = os.path.join(clax_agents_dir, '.env')
load_dotenv(dotenv_path)

OPTIMAL_ENTRY_URL = os.getenv("OPTIMAL_ENTRY_URL", "http://localhost:8001/optimal-entry-exit-price")
TOP10_MONTHLY_PICKS_URL = os.getenv("TOP10_MONTHLY_PICKS_URL", "http://localhost:8002/predict/top10")
PORTFOLIO_REBALANCE_URL = os.getenv("PORTFOLIO_REBALANCE_URL", "http://localhost:8003/api/v1/portfolio/rebalance")

# Request timeout in seconds
REQUEST_TIMEOUT = int(os.getenv("QUANT_BRIDGE_TIMEOUT", "15"))
