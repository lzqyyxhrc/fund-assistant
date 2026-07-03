"""快速验证 V2 评分系统"""
import sys
sys.path.insert(0, '.')

from services.valuation_scoring import (
    get_valuation_overview, get_portfolio_suggestion,
    score_asset, _score_from_interval
)

# 测试常识区间评分
print("=== 常识区间评分测试:")
print(f"  PE=12 (便宜): {_score_from_interval(12, 15, 22, 32, inverse=False):.1f}")
print(f"  PE=22 (中位): {_score_from_interval(22, 15, 22, 32, inverse=False):.1f}")
print(f"  PE=32 (昂贵): {_score_from_interval(32, 15, 22, 32, inverse=False):.1f}")
print(f"  股息率=2% (昂贵): {_score_from_interval(2.0, 5.5, 4.5, 3.0, inverse=True):.1f}")
print(f"  股息率=6% (便宜): {_score_from_interval(6.0, 5.5, 4.5, 3.0, inverse=True):.1f}")
print()

# 测试综合评分
print("=== 综合评分 (当前数据库) ===")
overview = get_valuation_overview()
for k, v in overview["assets"].items():
    print(f"  {k}: score={v['score']}, band={v['band']}, mult={v['invest_multiplier']}, macro={v['macro_factor']}")
    for m in v["metrics"]:
        print(f"    - {m['label']}: cur={m['current']}, score={m['score']}, reliability={m.get('reliability')}")
print()

# 测试组合建议
print("=== 组合建议 (¥1000) ===")
sug = get_portfolio_suggestion(1000.0)
for s in sug:
    print(f"  {s['label']}: ¥{s['amount']:.0f} ({s['ratio']:.0f}%) x{s['multiplier']}")

print("\n✅ V2 验证完成")
