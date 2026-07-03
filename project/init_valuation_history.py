"""
估值历史数据初始化脚本
==================================

用于从 FRED / FMP 拉取较长时间段的估值历史数据，
为"估值评分系统"提供足够的历史样本量。

使用方法：
  1) 先在 app.py 的 UI 或直接通过以下命令配置 API Key：
        python init_valuation_history.py --set-fmp YOUR_FMP_KEY
        python init_valuation_history.py --set-fred YOUR_FRED_KEY

  2) 然后执行初始化：
        python init_valuation_history.py

  3) 只获取某个来源：
        python init_valuation_history.py --only fred
        python init_valuation_history.py --only qqq
        python init_valuation_history.py --only csi

注意：
  - FMP 的 ratios-ttm 只返回"当前值"（历史需要用其它 endpoint）
  - FRED 可以一次拉取长达数年的数据
  - 中证红利通过 AkShare stock_zh_index_value_csindex 通常只返回"当前"
    估值数据（或较短历史）。如需更长的历史 PE/PB，需要从其它来源获取。
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

import pandas as pd

from services.valuation_fetcher import (
    fetch_all_valuations,
    fetch_fred_metrics,
    fetch_danjuan_valuation,
    get_api_key,
    set_api_key,
)
from services.valuation_scoring import get_valuation_overview
from services.database import bulk_upsert_valuation_metrics, get_valuation_history


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _check_keys():
    fmp = get_api_key("fmp")
    fred = get_api_key("fred")
    logger.info(f"当前 FMP API Key: {'已配置' if fmp else '未配置'}")
    logger.info(f"当前 FRED API Key: {'已配置' if fred else '未配置'}")
    if not fmp and not fred:
        logger.warning("两个 API Key 都未配置，只能获取 AkShare 的中证红利数据")


def _show_summary():
    overview = get_valuation_overview()
    print("\n=== 三大资产估值总览 ===")
    for a in ["nasdaq", "dividend", "gold"]:
        o = overview[a]
        score = o["score"]
        print(f"  [{a.upper()}] 分数: {score:.1f} | {o.get('recommendation')}")
        for m in o.get("metrics", []):
            print(f"     - {m['label']}: 当前={m['current']}, 分位={m['percentile']*100:.0f}%, "
                  f"评分={m['score']:.0f}, 样本={m['data_points']}")


def main():
    parser = argparse.ArgumentParser(description="估值历史数据初始化")
    parser.add_argument("--set-fmp", type=str, help="设置 FMP API Key")
    parser.add_argument("--set-fred", type=str, help="设置 FRED API Key")
    parser.add_argument("--only", type=str, choices=["fred", "danjuan"],
                        help="只获取某个来源的数据")
    parser.add_argument("--days", type=int, default=365,
                        help="FRED 历史数据天数（默认 365 天 = 1 年）")
    parser.add_argument("--summary", action="store_true", help="只显示当前估值总览")
    args = parser.parse_args()

    if args.set_fmp:
        set_api_key("fmp", args.set_fmp.strip())
        logger.info("FMP Key 已保存")
        return
    if args.set_fred:
        set_api_key("fred", args.set_fred.strip())
        logger.info("FRED Key 已保存")
        return

    _check_keys()

    if args.summary:
        _show_summary()
        return

    logger.info(f"开始初始化估值数据 (FRED 历史={args.days} 天)")

    if args.only == "fred":
        fetch_fred_metrics(history_days=args.days)
    elif args.only == "danjuan":
        fetch_danjuan_valuation(force=True)
    else:
        # 完整初始化
        fetch_danjuan_valuation(force=True)
        fetch_fred_metrics(history_days=args.days)

    logger.info("初始化完成！")
    _show_summary()


if __name__ == "__main__":
    main()
