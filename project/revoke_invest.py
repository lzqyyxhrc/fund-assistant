#!/usr/bin/env python3
"""
撤回指定日期的定投记录
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INVEST_HISTORY_PATH = "invest_history.json"
FUNDS_CONFIG_PATH = "funds_config.json"

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def revoke_invest(date_to_revoke):
    history = load_json(INVEST_HISTORY_PATH)
    config = load_json(FUNDS_CONFIG_PATH)

    record_to_revoke = None
    for i, record in enumerate(history):
        if record["date"] == date_to_revoke:
            record_to_revoke = history.pop(i)
            break

    if not record_to_revoke:
        print(f"错误: 未找到 {date_to_revoke} 的定投记录")
        return False

    print(f"找到定投记录: {date_to_revoke}, 总金额: ¥{record_to_revoke['total_amount']:.2f}")
    print("\n撤销以下交易:")
    print("-" * 60)

    for trans in record_to_revoke["transactions"]:
        code = trans["code"]
        shares_to_revoke = trans["shares"]
        category = trans["category"]
        name = trans["name"]
        amount = trans["amount"]

        print(f"  {category:8} | {code} | -{shares_to_revoke:.4f} 份 | -¥{amount:.2f}")

        for fund in config["funds"].get(category, []):
            if fund["code"] == code:
                old_shares = fund["shares"]
                new_shares = old_shares - shares_to_revoke

                if new_shares < 0:
                    print(f"  警告: {code} 份额可能不足")

                fund["shares"] = round(new_shares, 4)
                break

    print("-" * 60)

    save_json(INVEST_HISTORY_PATH, history)
    save_json(FUNDS_CONFIG_PATH, config)

    print("\n已成功撤回 %s 的定投记录" % date_to_revoke)
    print("持仓已更新")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python revoke_invest.py 2026-06-01")
        sys.exit(1)

    date_to_revoke = sys.argv[1]

    print("=" * 60)
    print("  定投撤回工具")
    print("=" * 60)
    print(f"\n将撤回日期: {date_to_revoke} 的定投记录")
    print("\n确认继续? (y/n): ", end="")
    confirm = input().strip().lower()

    if confirm == "y":
        revoke_invest(date_to_revoke)
    else:
        print("已取消")
