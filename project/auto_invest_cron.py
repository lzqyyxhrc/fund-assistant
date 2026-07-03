#!/usr/bin/env python3
"""
基金自动定投定时执行脚本
使用方法：
  - 执行定投（建议早上10点）：python auto_invest_cron.py --invest
  - 确认份额（建议晚上10点）：python auto_invest_cron.py --confirm
  - 定投+确认（不推荐）：python auto_invest_cron.py --invest --confirm
  - 生成日报：python auto_invest_cron.py --report -k YOUR_API_KEY

配合操作系统定时任务设置：
  - 每日 10:00：执行定投任务 python auto_invest_cron.py --invest
  - 每日 22:00：执行确认份额任务 python auto_invest_cron.py --confirm
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 自动加载项目根目录 .env（若存在），把 DEEPSEEK_API_KEY/FEISHU_WEBHOOK 等注入环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

from datetime import datetime
from services.storage import load_config, save_config
from services.fund_fetcher import get_fund_batch_net_value
from services.auto_invest import load_auto_invest_config, check_and_execute_auto_invest, confirm_pending_shares

def generate_report_after_invest(api_key=None, feishu_webhook=None):
    """定投完成后生成日报"""
    try:
        from daily_report import generate_daily_report, save_report, send_to_feishu
        print("\n生成投资日报...")
        
        report = generate_daily_report(api_key=api_key)
        if report:
            save_report(report)
            print("日报已生成")
            
            if feishu_webhook:
                print("发送到飞书...")
                if send_to_feishu(report, feishu_webhook):
                    print("已发送到飞书")
                else:
                    print("飞书发送失败")
            
            return True
        else:
            print("日报生成失败")
            return False
    except Exception as e:
        print("日报生成出错: %s" % str(e))
        return False

def main():
    parser = argparse.ArgumentParser(description="基金自动定投执行脚本")
    parser.add_argument("--invest", "-i", action="store_true", help="执行定投操作（建议早上10点执行）")
    parser.add_argument("--confirm", "-c", action="store_true", help="确认到期的待确认份额（建议晚上10点执行）")
    parser.add_argument("--report", "-r", action="store_true", help="生成投资日报")
    parser.add_argument("--valuation", "-v", action="store_true", help="获取估值评分数据（建议晚上10点执行）")
    parser.add_argument("--api-key", "-k", help="DeepSeek API Key（用于生成日报）")
    parser.add_argument("--feishu", "-f", help="飞书 Webhook URL")
    args = parser.parse_args()
    
    # 检查至少指定了一个操作
    if not args.invest and not args.confirm and not args.report and not args.valuation:
        parser.print_help()
        print("\n错误：请至少指定一个操作 --invest、--confirm、--report 或 --valuation")
        return
    
    print("=== 基金自动定投执行脚本 ===")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.report:
        print("报告模式：将生成投资日报")
    
    try:
        funds_config = load_config()
        
        # 确认份额操作
        if args.confirm:
            print("执行确认份额操作...")
            all_codes = []
            for category in ["nasdaq", "dividend", "gold"]:
                for fund in funds_config["funds"].get(category, []):
                    if fund["code"]:
                        all_codes.append(fund["code"])
            
            if all_codes:
                print("获取基金净值...")
                net_values = get_fund_batch_net_value(all_codes)
                
                if net_values:
                    print("成功获取基金净值")
                    print("检查待确认份额...")
                    confirmed_count = confirm_pending_shares(funds_config, net_values)
                    if confirmed_count > 0:
                        print("已确认 %d 笔待确认份额" % confirmed_count)
                        save_config(funds_config)
                    else:
                        print("暂无到期待确认份额")
                else:
                    print("未能获取基金净值，跳过确认操作")
            else:
                print("未配置基金代码，跳过确认操作")
        
        # 定投操作
        if args.invest:
            print("执行定投操作...")
            auto_config = load_auto_invest_config()
            
            if not auto_config.get("enabled", False):
                print("自动定投未启用")
                return
            
            all_codes = []
            for category in ["nasdaq", "dividend", "gold"]:
                for fund in funds_config["funds"].get(category, []):
                    if fund["code"]:
                        all_codes.append(fund["code"])
            
            if not all_codes:
                print("未配置基金代码")
                return
            
            print("获取基金净值...")
            net_values = get_fund_batch_net_value(all_codes)
            
            if not net_values:
                print("未能获取基金净值")
                return
            
            print("成功获取基金净值")
            
            transactions, total_amount = check_and_execute_auto_invest(funds_config, net_values)
            
            if transactions:
                print("自动定投完成！共投入 ¥%.2f" % total_amount)
                save_config(funds_config)
                print("持仓已更新")
                
                for trans in transactions:
                    print("  - %s: ¥%.2f (%.4f份)" % (trans['name'], trans['amount'], trans['shares']))
            else:
                print("今日无需定投（可能已执行或未到定投时间）")
        
        # 生成日报
        if args.report:
            print("\n" + "="*50)
            generate_report_after_invest(api_key=args.api_key, feishu_webhook=args.feishu)
        
        # 获取估值评分数据
        if args.valuation:
            print("\n" + "="*50)
            print("获取估值数据...")
            try:
                from services.valuation_fetcher import fetch_all_valuations
                from services.valuation_scoring import get_valuation_overview
                results = fetch_all_valuations()
                if results:
                    print("估值数据获取成功: %s" % list(results.keys()))
                    overview = get_valuation_overview()
                    for a in ["nasdaq", "dividend", "gold"]:
                        o = overview[a]
                        print("  [%s] 分数: %.1f | %s" % (a.upper(), o["score"] if o["score"] else -1, o.get("recommendation")))
                else:
                    print("未获取到估值数据（请检查 API Key 是否配置）")
            except Exception as e:
                print("估值数据获取失败: %s" % str(e))
                import traceback
                traceback.print_exc()
            
    except Exception as e:
        print("执行失败: %s" % str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()