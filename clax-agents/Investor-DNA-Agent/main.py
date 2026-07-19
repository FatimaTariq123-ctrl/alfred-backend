import sys
sys.path.append('/home/ummara/clax/investor-dna')

import uvicorn
from db.schema import create_table
from api.profile_service import app

if __name__ == "__main__":
    # Ensure table exists on startup
    print("🔧 Initializing database...")
    create_table()
    
    print("🚀 Starting Investor DNA Profile Service...")
    uvicorn.run(app, host="0.0.0.0", port=8000)