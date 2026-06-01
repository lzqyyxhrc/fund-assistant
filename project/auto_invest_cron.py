#!/usr/bin/env python3
"""
基金自动定投定时执行脚本
使用方法：
  - 纯定投：python auto_invest_cron.py
  - 定投+报告：python auto_invest_cron.py --report -k YOUR_API_KEY
配合操作系统定时任务（如Windows任务计划程序）在每天22:00运行
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from services.storage import load_config, save_config
from services.fund_fetcher import get_fund_batch_net_value
from services.auto_invest import load_auto_invest_config, check_and_execute_auto_invest

def generate_report_after_invest(api_key=None, feishu_webhook=None):
    """定投完成后生成日报"""
    try:
        from daily_report import generate_daily_report, save_report, send_to_feishu
        print("\n📊 生成投资日报...")
        
        report = generate_daily_report(api_key=api_key)
        if report:
            save_report(report)
            print("✅ 日报已生成")
            
            if feishu_webhook:
                print("📤 发送到飞书...")
                if send_to_feishu(report, feishu_webhook):
                    print("✅ 已发送到飞书")
                else:
                    print("⚠️ 飞书发送失败")
            
            return True
        else:
            print("⚠️ 日报生成失败")
            return False
    except Exception as e:
        print(f"⚠️ 日报生成出错: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="基金自动定投执行脚本")
    parser.add_argument("--report", "-r", action="store_true", help="定投完成后生成日报")
    parser.add_argument("--api-key", "-k", help="DeepSeek API Key（用于生成日报）")
    parser.add_argument("--feishu", "-f", help="飞书 Webhook URL")
    args = parser.parse_args()
    
    print("=== 基金自动定投执行脚本 ===")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.report:
        print("📝 报告模式：定投完成后将生成日报")
    
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
        
        if args.report:
            print("\n" + "="*50)
            generate_report_after_invest(api_key=args.api_key, feishu_webhook=args.feishu)
            
    except Exception as e:
        print(f"❌ 执行失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()