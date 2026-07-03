#!/usr/bin/env python3
"""
数据库修改脚本 - 支持命令行参数
使用方法: python db_update.py <操作> [参数]
"""

import sys
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "fund_assistant.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_update_position(code, shares=None, cost_price=None, name=None):
    """更新基金持仓"""
    with get_connection() as conn:
        updates = []
        params = []
        if shares is not None:
            updates.append("shares = ?")
            params.append(float(shares))
        if cost_price is not None:
            updates.append("cost_price = ?")
            params.append(float(cost_price))
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(code)
            sql = f"UPDATE fund_positions SET {', '.join(updates)} WHERE code = ?"
            conn.execute(sql, params)
            print(f"OK: 已更新基金 {code}")
        else:
            print("ERROR: 没有提供任何更新字段")


def cmd_update_target(category, weight):
    """更新组合目标权重"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_targets(category, target_weight) VALUES(?, ?)",
            (category, float(weight))
        )
    print(f"OK: 已更新 {category} 权重为 {weight}")


def cmd_update_auto_invest(code, amount):
    """更新定投计划金额"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO auto_invest_plans(code, amount) VALUES(?, ?)",
            (code, float(amount))
        )
    print(f"OK: 已更新 {code} 定投金额为 {amount}")


def cmd_add_position(code, category, name, shares=0, cost_price=0):
    """添加基金持仓"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fund_positions(code, category, name, shares, cost_price, updated_at) VALUES(?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (code, category, name, float(shares), float(cost_price))
        )
    print(f"OK: 已添加基金 {code}")


def cmd_delete_position(code):
    """删除基金持仓"""
    with get_connection() as conn:
        conn.execute("DELETE FROM fund_positions WHERE code = ?", (code,))
        conn.execute("DELETE FROM pending_orders WHERE fund_code = ?", (code,))
    print(f"OK: 已删除基金 {code}")


def cmd_show_positions():
    """显示基金持仓"""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM fund_positions ORDER BY category")
        for row in cursor.fetchall():
            print(f"[{row['category']}] {row['code']} {row['name']} | 份额:{row['shares']:.4f} | 成本价:{row['cost_price']:.4f}")


def cmd_show_targets():
    """显示目标权重"""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM portfolio_targets")
        for row in cursor.fetchall():
            print(f"{row['category']}: {row['target_weight']*100:.0f}%")


def cmd_show_auto_invest():
    """显示定投计划"""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM auto_invest_plans")
        for row in cursor.fetchall():
            print(f"{row['code']}: {row['amount']:.2f}")


def show_help():
    print("数据库修改工具")
    print("用法: python db_update.py <操作> [参数]")
    print("")
    print("操作列表:")
    print("  show_positions          显示所有基金持仓")
    print("  show_targets            显示组合目标权重")
    print("  show_auto_invest        显示定投计划")
    print("  update_position <代码> [份额] [成本价] [名称]")
    print("  update_target <类别> <权重>")
    print("  update_auto_invest <代码> <金额>")
    print("  add_position <代码> <类别> <名称> [份额] [成本价]")
    print("  delete_position <代码>")
    print("")
    print("示例:")
    print("  python db_update.py update_position 008164 10000 1.05")
    print("  python db_update.py update_target nasdaq 0.45")
    print("  python db_update.py update_auto_invest 008164 100")


def main():
    if len(sys.argv) < 2:
        show_help()
        return

    cmd = sys.argv[1]

    if cmd == "show_positions":
        cmd_show_positions()
    elif cmd == "show_targets":
        cmd_show_targets()
    elif cmd == "show_auto_invest":
        cmd_show_auto_invest()
    elif cmd == "update_position":
        if len(sys.argv) < 3:
            print("ERROR: 需要基金代码")
            return
        code = sys.argv[2]
        shares = sys.argv[3] if len(sys.argv) > 3 else None
        cost_price = sys.argv[4] if len(sys.argv) > 4 else None
        name = sys.argv[5] if len(sys.argv) > 5 else None
        cmd_update_position(code, shares, cost_price, name)
    elif cmd == "update_target":
        if len(sys.argv) < 4:
            print("ERROR: 需要类别和权重")
            return
        cmd_update_target(sys.argv[2], sys.argv[3])
    elif cmd == "update_auto_invest":
        if len(sys.argv) < 4:
            print("ERROR: 需要基金代码和金额")
            return
        cmd_update_auto_invest(sys.argv[2], sys.argv[3])
    elif cmd == "add_position":
        if len(sys.argv) < 5:
            print("ERROR: 需要代码、类别、名称")
            return
        code = sys.argv[2]
        category = sys.argv[3]
        name = sys.argv[4]
        shares = sys.argv[5] if len(sys.argv) > 5 else 0
        cost_price = sys.argv[6] if len(sys.argv) > 6 else 0
        cmd_add_position(code, category, name, shares, cost_price)
    elif cmd == "delete_position":
        if len(sys.argv) < 3:
            print("ERROR: 需要基金代码")
            return
        cmd_delete_position(sys.argv[2])
    else:
        print(f"ERROR: 未知操作 {cmd}")
        show_help()


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: 数据库不存在 {DB_PATH}")
        sys.exit(1)
    main()