#!/usr/bin/env python3
"""
基金自动定投定时执行脚本
使用方法：配合操作系统定时任务（如Windows任务计划程序）在每天22:00运行
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.storage import load_config, save_config
from services.fund_fetcher import get_fund_batch_net_value
from services.auto_invest import load_auto_invest_config, check_and_execute_auto_invest

def main():
    print("=== 基金自动定投执行脚本 ===")
    print(f"执行时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        funds_config = load_config()
        auto_config = load_auto_invest_config()
        
        if not auto_config.get("enabled", False):
            print("❌ 自动定投未启用")
            return
        
        all_codes = []
        for category in ["nasdaq", "dividend", "gold"]:
            for fund in funds_config["funds"].get(category, []):
                if fund["code"]:
                    all_codes.append(fund["code"])
        
        if not all_codes:
            print("❌ 未配置基金代码")
            return
        
        print("📡 获取基金净值...")
        net_values = get_fund_batch_net_value(all_codes)
        
        if not net_values:
            print("❌ 未能获取基金净值")
            return
        
        print("✅ 成功获取基金净值")
        
        transactions, total_amount = check_and_execute_auto_invest(funds_config, net_values)
        
        if transactions:
            print(f"✅ 自动定投完成！共投入 ¥{total_amount:.2f}")
            save_config(funds_config)
            print("✅ 持仓已更新")
            
            for trans in transactions:
                print(f"  - {trans['name']}: ¥{trans['amount']:.2f} ({trans['shares']:.4f}份)")
        else:
            print("ℹ️ 今日无需定投（可能已执行或未到定投时间）")
            
    except Exception as e:
        print(f"❌ 执行失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()