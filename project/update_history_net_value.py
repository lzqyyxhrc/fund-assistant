#!/usr/bin/env python3
"""
批量更新基金历史净值
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.storage import load_config
from services.fund_fetcher import batch_update_history_net_value

def main():
    print("=== 基金历史净值批量更新工具 ===")
    
    config = load_config()
    
    # 获取所有基金代码
    all_codes = []
    for category in ["nasdaq", "dividend", "gold"]:
        for fund in config["funds"].get(category, []):
            if fund["code"]:
                all_codes.append(fund["code"])
    
    if not all_codes:
        print("未配置基金代码")
        return
    
    print(f"找到 {len(all_codes)} 只基金")
    print(f"基金列表: {', '.join(all_codes)}")
    print("\n开始获取历史净值（今年以来）...")
    
    batch_update_history_net_value(all_codes)
    
    print("\n=== 更新完成 ===")

if __name__ == "__main__":
    main()