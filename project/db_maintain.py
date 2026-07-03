#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库数据维护工具
用于查看和修改 SQLite 数据库中的数据
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


def show_tables():
    """显示所有表"""
    with get_connection() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
    print("数据库表列表:")
    for i, table in enumerate(tables, 1):
        print(f"  {i}. {table}")
    return tables


def show_table_data(table_name, limit=10):
    """显示表内容"""
    try:
        with get_connection() as conn:
            # 获取列名
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            
            # 获取数据
            cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,))
            rows = cursor.fetchall()
            
        print(f"\n表: {table_name}")
        print(f"列: {', '.join(columns)}")
        print("-" * 80)
        
        if not rows:
            print("  (空表)")
            return
            
        for row in rows:
            values = [str(row[col]) for col in columns]
            print(f"  {' | '.join(values)}")
            
    except sqlite3.Error as e:
        print(f"  查询失败: {e}")


def update_fund_position(code, shares=None, cost_price=None, name=None):
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
            print(f"✅ 已更新基金 {code} 的持仓")
        else:
            print("❌ 没有提供任何更新字段")


def update_portfolio_target(category, target_weight):
    """更新组合目标权重"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_targets(category, target_weight) VALUES(?, ?)",
            (category, float(target_weight))
        )
    print(f"✅ 已更新 {category} 的目标权重为 {target_weight}")


def add_fund_position(code, category, name, shares=0, cost_price=0):
    """添加基金持仓"""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO fund_positions(code, category, name, shares, cost_price, updated_at)
            VALUES(?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (code, category, name, float(shares), float(cost_price))
        )
    print(f"✅ 已添加/更新基金: {code} ({name})")


def delete_fund_position(code):
    """删除基金持仓"""
    with get_connection() as conn:
        conn.execute("DELETE FROM fund_positions WHERE code = ?", (code,))
        conn.execute("DELETE FROM pending_orders WHERE fund_code = ?", (code,))
    print(f"✅ 已删除基金 {code} 的持仓和待确认订单")


def show_fund_positions():
    """显示所有基金持仓"""
    print("\n=== 基金持仓 ===")
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM fund_positions ORDER BY category, rowid").fetchall()
    
    if not rows:
        print("  暂无持仓")
        return
        
    for row in rows:
        total_value = row["shares"] * row["cost_price"]
        print(f"  [{row['category']}] {row['code']} {row['name']}")
        print(f"      份额: {row['shares']:.4f} | 成本价: {row['cost_price']:.4f} | 成本金额: {total_value:.2f}")
        print(f"      更新时间: {row['updated_at']}")


def show_pending_orders():
    """显示待确认订单"""
    print("\n=== 待确认订单 ===")
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM pending_orders WHERE status='pending'").fetchall()
    
    if not rows:
        print("  无待确认订单")
        return
        
    for row in rows:
        print(f"  {row['id']}. {row['fund_code']} | 金额: {row['amount']:.2f} | 日期: {row['pending_date']}")


def main():
    print("=" * 60)
    print("  SQLite 数据库维护工具")
    print("=" * 60)
    
    while True:
        print("\n请选择操作:")
        print("  1. 查看所有表")
        print("  2. 查看表内容")
        print("  3. 查看基金持仓")
        print("  4. 查看待确认订单")
        print("  5. 更新基金持仓")
        print("  6. 添加/更新基金")
        print("  7. 删除基金持仓")
        print("  8. 更新组合目标权重")
        print("  9. 退出")
        
        choice = input("\n输入选择 [1-9]: ").strip()
        
        if choice == "1":
            show_tables()
            
        elif choice == "2":
            table = input("输入表名: ").strip()
            show_table_data(table)
            
        elif choice == "3":
            show_fund_positions()
            
        elif choice == "4":
            show_pending_orders()
            
        elif choice == "5":
            code = input("基金代码: ").strip()
            shares = input("新份额 (回车跳过): ").strip() or None
            cost_price = input("新成本价 (回车跳过): ").strip() or None
            name = input("新名称 (回车跳过): ").strip() or None
            update_fund_position(code, shares, cost_price, name)
            
        elif choice == "6":
            code = input("基金代码: ").strip()
            category = input("类别 (nasdaq/dividend/gold): ").strip()
            name = input("基金名称: ").strip()
            shares = input("份额 (默认0): ").strip() or 0
            cost_price = input("成本价 (默认0): ").strip() or 0
            add_fund_position(code, category, name, shares, cost_price)
            
        elif choice == "7":
            code = input("要删除的基金代码: ").strip()
            confirm = input(f"确定删除 {code} 吗? (y/N): ").strip()
            if confirm.lower() == "y":
                delete_fund_position(code)
            else:
                print("取消操作")
                
        elif choice == "8":
            category = input("类别 (nasdaq/dividend/gold): ").strip()
            weight = input("目标权重: ").strip()
            update_portfolio_target(category, weight)
            
        elif choice == "9":
            print("退出")
            break
            
        else:
            print("无效选择，请输入 1-9")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"错误: 数据库文件不存在 {DB_PATH}")
        sys.exit(1)
    main()