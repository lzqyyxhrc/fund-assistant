import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "fund_assistant.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print("=== 数据库表列表 ===")
for i, t in enumerate(tables, 1):
    print(f"{i}. {t}")

print("\n=== 各表记录数 ===")
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"{t}: {count} 条")

print("\n=== 基金持仓 ===")
cursor = conn.execute("SELECT * FROM fund_positions ORDER BY category")
for row in cursor.fetchall():
    print(f"[{row['category']}] {row['code']} {row['name']}")
    print(f"    份额: {row['shares']:.4f} | 成本价: {row['cost_price']:.4f}")

print("\n=== 组合目标权重 ===")
cursor = conn.execute("SELECT * FROM portfolio_targets")
for row in cursor.fetchall():
    print(f"{row['category']}: {row['target_weight']*100:.0f}%")

print("\n=== 定投计划 ===")
cursor = conn.execute("SELECT * FROM auto_invest_plans ORDER BY rowid")
for row in cursor.fetchall():
    print(f"{row['code']}: {row['amount']:.2f}")

conn.close()