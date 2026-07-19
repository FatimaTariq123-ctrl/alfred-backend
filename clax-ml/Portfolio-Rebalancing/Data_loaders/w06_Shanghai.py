# Data_loaders/w06_Shanghai.py
# --------------------
import os
import time
import pandas as pd
import yfinance as yf
from pathlib import Path
import logging
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ Constants ------------------ #
SHANGHAI_SYMBOLS = [
    "600000.SS",  # Shanghai Pudong Development Bank
    "600036.SS",  # China Merchants Bank
    "600276.SS",  # Jiangsu Hengrui Medicine
    "600519.SS",  # Kweichow Moutai
    "600887.SS",  # Inner Mongolia Yili Industrial Group
    "600009.SS",  # Shanghai International Airport
    "600016.SS",  # China Minsheng Banking Corp
    "600028.SS",  # China Petroleum & Chemical Corporation
    "600030.SS",  # CITIC Securities
    "600031.SS",  # Sany Heavy Industry
    "600048.SS",  # Poly Developments and Holdings Group
    "600050.SS",  # China United Network Communications
    "600061.SS",  # SDIC Essence Holdings
    "600085.SS",  # Beijing Tongrentang
    "600089.SS",  # TBEA
    "600104.SS",  # SAIC Motor Corporation
    "600109.SS",  # Sinolink Securities
    "600111.SS",  # China Northern Rare Earth (Group) High-Tech
    "600115.SS",  # China Eastern Airlines
    "600118.SS",  # China Spacesat
    "600132.SS",  # Chongqing Brewery
    "600150.SS",  # China CSSC Holdings
    "600176.SS",  # China Jushi
    "600177.SS",  # Youngor Group
    "600196.SS",  # Fosun Pharmaceutical
    "600208.SS",  # Xinjiang Guanghui Industry Investment
    "600233.SS",  # YTO Express Group
    "600276.SS",  # Jiangsu Hengrui Medicine
    "600309.SS",  # Wanhua Chemical Group
    "600332.SS",  # Guangzhou Baiyun Chemical Industry
    "600346.SS",  # Hengli Petrochemical
    "600352.SS",  # Zhejiang Longsheng Group
    "600362.SS",  # Jiangxi Copper
    "600383.SS",  # Gemdale Corporation
    "600406.SS",  # Nari Technology Development
    "600436.SS",  # Zhangzhou Pientzehuang Pharmaceutical
    "600438.SS",  # Tongwei
    "600519.SS",  # Kweichow Moutai
    "600547.SS",  # Shandong Gold Mining
    "600570.SS",  # Hundsun Technologies
    "600585.SS",  # Anhui Conch Cement
    "600588.SS",  # Yonyou Network Technology
    "600600.SS",  # Tsingtao Brewery
    "600660.SS",  # Fuyao Glass Industry Group
    "600690.SS",  # Haier Smart Home
    "600741.SS",  # HUAYU Automotive Systems
    "600745.SS",  # Wingtech Technology
    "600760.SS",  # AVIC Shenyang Aircraft Industry Group
    "600795.SS",  # GD Power Development
    "600837.SS",  # Haitong Securities
    "600887.SS",  # Inner Mongolia Yili Industrial Group
    "600893.SS",  # AVIC Helicopter
    "600900.SS",  # China Yangtze Power
    "600919.SS",  # Bank of Jiangsu
    "600926.SS",  # Bank of Hangzhou
    "600958.SS",  # Orient Securities
    "600989.SS",  # Ningxia Baofeng Energy Group
    "600999.SS",  # China Merchants Securities
    "601006.SS",  # Daqin Railway
    "601009.SS",  # Bank of Nanjing
    "601012.SS",  # Longi Green Energy Technology
    "601021.SS",  # Spring Airlines
    "601066.SS",  # Zhongnan Construction Group
    "601088.SS",  # China Shenhua Energy
    "601100.SS",  # Henan Shuanghui Investment & Development
    "601111.SS",  # Air China
    "601117.SS",  # China National Chemical Engineering
    "601138.SS",  # Foxconn Industrial Internet
    "601155.SS",  # New China Life Insurance
    "601166.SS",  # Industrial Bank
    "601169.SS",  # Bank of Beijing
    "601186.SS",  # China Railway Construction Corporation
    "601211.SS",  # Guotai Junan Securities
    "601216.SS",  # Inner Mongolia Junzheng Energy & Chemical Group
    "601225.SS",  # Shaanxi Coal Industry
    "601229.SS",  # Bank of Shanghai
    "601236.SS",  # Guangzhou Rural Commercial Bank
    "601238.SS",  # Guangzhou Automobile Group
    "601288.SS",  # Agricultural Bank of China
    "601318.SS",  # Ping An Insurance
    "601319.SS",  # Bank of China
    "601328.SS",  # Bank of Communications
    "601336.SS",  # New China Life Insurance
    "601360.SS",  # 360 Security Technology
    "601377.SS",  # Industrial and Commercial Bank of China
    "601390.SS",  # China Railway Group
    "601398.SS",  # Industrial and Commercial Bank of China
    "601600.SS",  # Aluminum Corporation of China
    "601601.SS",  # China Pacific Insurance (Group)
    "601607.SS",  # Shanghai Pharmaceuticals Holding
    "601618.SS",  # Metallurgical Corporation of China
    "601628.SS",  # China Life Insurance
    "601633.SS",  # Great Wall Motor
    "601668.SS",  # China State Construction Engineering
    "601669.SS",  # Power Construction Corporation of China
    "601688.SS",  # Huatai Securities
    "601689.SS",  # Ningbo Tuopuson Medical Technology
    "601698.SS",  # China Satcom
    "601727.SS",  # Shanghai Electric Group
    "601766.SS",  # CRRC Corporation
    "601788.SS",  # Everbright Securities
    "601800.SS",  # China Communications Construction Company
    "601808.SS",  # China Oilfield Services
    "601818.SS",  # China Everbright Bank
    "601828.SS",  # Bank of Chengdu
    "601838.SS",  # Bank of Chengdu
    "601857.SS",  # PetroChina
    "601866.SS",  # COSCO SHIPPING Holdings
    "601872.SS",  # China Merchants Energy Shipping
    "601877.SS",  # Zhejiang Chint Electrics
    "601878.SS",  # Zhejiang Hailiang
    "601881.SS",  # China Galaxy Securities
    "601888.SS",  # China International Travel Service
]

OUTPUT_PATH = "outputs/06_Shanghai_OHLCV.csv"

def fetch_data(symbols, start="2015-01-01", end=None, batch_size=50):
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    all_data = []
    num_batches = (len(symbols) + batch_size - 1) // batch_size
    for i in tqdm(range(0, len(symbols), batch_size), desc="Fetching Shanghai Data Batches"):
        batch = symbols[i:i+batch_size]
        try:
            df = yf.download(
                batch, start=start, end=end, group_by="ticker",
                auto_adjust=True, threads=True, progress=False
            )
            if df is not None and not df.empty:
                all_data.append(df)
        except Exception as e:
            logger.error(f"Error fetching batch {i//batch_size+1}: {e}")
        time.sleep(1)  # Be respectful to the API
    return all_data

def run_pipeline():
    logger.info("====== Starting Data Loader 06: Shanghai Stock Data Fetching ======")
    start_time = time.time()

    symbols = SHANGHAI_SYMBOLS[:50]  # Limit to first 50 for testing
    logger.info(f"Fetching data for {len(symbols)} Shanghai stocks...")

    # Fetch data
    data_batches = fetch_data(symbols)
    logger.info(f"Fetched data in batches.")

    # Reformat into DataFrame
    frames = []
    for sym in tqdm(symbols, desc="Reformatting Data"):
        symbol_frames = []
        for batch_df in data_batches:
            if batch_df is None or getattr(batch_df, "empty", True):
                continue
            if isinstance(batch_df.columns, pd.MultiIndex):
                if sym in batch_df.columns.get_level_values(0):
                    symbol_data = batch_df[sym].copy()
                    symbol_data.columns = symbol_data.columns.droplevel(0) if symbol_data.columns.nlevels > 1 else symbol_data.columns
                    symbol_frames.append(symbol_data)
            elif sym in batch_df.columns:
                symbol_frames.append(batch_df[[sym]])

        if symbol_frames:
            df = pd.concat(symbol_frames)
            if df is not None and not df.empty:
                df["Ticker"] = sym
                df = df.reset_index().rename(columns={"Date": "date"})
                frames.append(df)

    if frames:
        sh_df = pd.concat(frames, axis=0)
        sh_df = sh_df.sort_values(["Ticker", "date"])
        Path("outputs").mkdir(parents=True, exist_ok=True)
        sh_df.to_csv(OUTPUT_PATH, index=False)
        logger.info(f"✅ Saved Shanghai data to {OUTPUT_PATH} with shape {sh_df.shape}")
    else:
        logger.error("❌ No data fetched for Shanghai stocks.")

    logger.info(f"Total time: {time.time() - start_time:.2f} seconds.")

if __name__ == "__main__":
    run_pipeline()