"""
指数历史数据下载脚本
用于下载黄金、红利、纳指100等指数的历史数据用于回测
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import os
import json
import sys

# 尝试导入yfinance用于下载美股数据
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("[WARN] yfinance not installed, US stock data will be limited")

# 设置输出编码为UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# 指数配置
INDEX_CONFIG = {
    "nasdaq100": {
        "name": "NASDAQ100",
        "code": "NDX",
        "us_code": "NDX"
    },
    "红利指数": {
        "name": "CSI Dividend Total Return",
        "code": "000015",
        "us_code": None,
        "total_return": True  # 标记为全收益指数
    },
    "黄金": {
        "name": "Gold",
        "code": "AU9999",
        "us_code": None
    }
}

def download_index_data(index_name, start_date=None, end_date=None, save_path="data/index"):
    """
    下载指数历史数据

    Args:
        index_name: 指数名称键名（如 "nasdaq100", "红利指数", "黄金"）
        start_date: 开始日期（YYYY-MM-DD格式），默认3年前
        end_date: 结束日期（YYYY-MM-DD格式），默认今天
        save_path: 保存路径

    Returns:
        DataFrame: 下载的数据
    """
    config = INDEX_CONFIG.get(index_name)
    if not config:
        print(f"[ERROR] Index config not found: {index_name}")
        return None

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    if start_date is None:
        start_date = "2016-01-01"

    print(f"\n[INFO] Downloading {config['name']} data ({start_date} to {end_date})...")

    try:
        df = None

        if index_name == "nasdaq100":
            # 使用yfinance下载纳斯达克100指数数据
            if YFINANCE_AVAILABLE:
                try:
                    ticker = yf.Ticker("^NDX")
                    df = ticker.history(start=start_date, end=end_date)

                    if df is not None and len(df) > 0:
                        df = df.reset_index()
                        df['date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
                        df = df[['date', 'Open', 'High', 'Low', 'Close', 'Volume']]
                        df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                        print(f"[OK] Downloaded {len(df)} records from Yahoo Finance")
                    else:
                        print(f"[WARN] No data available from Yahoo Finance")
                        return None
                except Exception as e:
                    print(f"[ERROR] Yahoo Finance download failed: {e}")
                    print(f"       Please download manually from:")
                    print(f"       https://finance.yahoo.com/quote/%5ENDX/history")
                    return None
            else:
                print(f"[WARN] yfinance not installed, please download manually")
                print(f"       Source: https://finance.yahoo.com/quote/%5ENDX/history")
                return None

        elif index_name == "红利指数":
            # 使用中证红利全收益指数（包含分红再投资）
            # 尝试使用全收益指数接口
            try:
                # 方法1：尝试使用中证全收益指数接口
                df = ak.stock_zh_index_daily(symbol="shH00015")  # H00015 是中证红利全收益指数
                df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                df['date'] = pd.to_datetime(df['date'])
                print(f"[OK] Downloaded CSI Dividend Total Return index (H00015)")
            except:
                # 方法2：如果全收益指数不可用，使用普通指数并提示
                print(f"[WARN] Total Return index not available, using price index instead")
                print(f"[INFO] Price index does not include dividend reinvestment")
                df = ak.stock_zh_index_daily(symbol="sh000015")
                df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                df['date'] = pd.to_datetime(df['date'])

            # 筛选日期范围
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

        elif index_name == "黄金":
            # 使用上海黄金交易所基准价格
            df = ak.spot_golden_benchmark_sge()
            df['date'] = pd.to_datetime(df['交易时间'])
            df = df[['date', '早盘价', '晚盘价']]
            df.columns = ['date', 'close', 'close_evening']

            # 筛选日期范围
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

            # 简化数据，只保留收盘价（使用晚盘价）
            df = df[['date', 'close_evening']].rename(columns={'close_evening': 'close'})

        if df is None or len(df) == 0:
            print(f"[WARN] No data available for {config['name']}, skipping...")
            return None

        # 保存数据
        os.makedirs(save_path, exist_ok=True)
        filename = f"{save_path}/{config['code']}_{datetime.now().strftime('%Y%m%d')}.csv"

        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"[OK] Data saved to: {filename}")
        print(f"     Total records: {len(df)}")

        return df

    except Exception as e:
        print(f"[ERROR] Download failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def download_all_index_data(save_path="data/index"):
    """下载所有配置的指数数据"""
    print("=" * 60)
    print("Downloading All Index Historical Data")
    print("=" * 60)

    results = {}
    for index_name in INDEX_CONFIG.keys():
        df = download_index_data(index_name, save_path=save_path)
        results[index_name] = df

    # 生成汇总报告
    print("\n" + "=" * 60)
    print("Download Summary")
    print("=" * 60)

    for index_name, df in results.items():
        config = INDEX_CONFIG[index_name]
        if df is not None and len(df) > 0:
            print(f"[OK] {config['name']}: {len(df)} records")

            # 打印数据范围
            if 'date' in df.columns:
                start = df['date'].min()
                end = df['date'].max()
                print(f"     Date range: {start.date()} to {end.date()}")
        else:
            print(f"[FAIL] {config['name']}: Download failed")

    return results


def load_index_data(index_code, data_dir="data/index"):
    """加载已下载的指数数据"""
    if not os.path.exists(data_dir):
        return None

    files = [f for f in os.listdir(data_dir) if f.startswith(index_code) and f.endswith('.csv')]

    if not files:
        return None

    # 使用最新的文件
    latest_file = sorted(files)[-1]
    filepath = os.path.join(data_dir, latest_file)

    df = pd.read_csv(filepath, encoding='utf-8-sig')

    # 统一日期列
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    elif '日期' in df.columns:
        df['date'] = pd.to_datetime(df['日期'])

    return df


def get_available_us_indices():
    """获取可用的美股指数列表"""
    print("[INFO] Fetching available US indices...")
    try:
        # 获取常见美股指数
        indices = {
            "NDX": "NASDAQ 100",
            "SPX": "S&P 500",
            "IXIC": "NASDAQ Composite",
            "DJI": "Dow Jones Industrial"
        }
        return indices
    except Exception as e:
        print(f"[ERROR] Failed to fetch indices: {e}")
        return {}


if __name__ == "__main__":
    # 测试下载
    download_all_index_data()

    # 打印保存的数据文件
    print("\n" + "=" * 60)
    print("Saved Data Files:")
    print("=" * 60)
    if os.path.exists("data/index"):
        for file in os.listdir("data/index"):
            if file.endswith('.csv'):
                filepath = os.path.join("data/index", file)
                size = os.path.getsize(filepath)
                print(f"  {file} ({size/1024:.1f} KB)")
    else:
        print("  No data files found.")
