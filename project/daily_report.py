"""
基金投资日报生成器
集成项目 V2 估值评分系统：估值评分 / 资产便宜度排名 / 组合配置建议 / 宏观因子
"""

import os
# 自动加载项目根目录 .env（若存在），把 DEEPSEEK_API_KEY/FEISHU_WEBHOOK 等注入环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

import json
import requests
import traceback
from datetime import datetime
from services.storage import load_config as load_config_from_db
from services.net_value_storage import load_net_value_history


# ============================================================
# 工具函数
# ============================================================
def load_config():
    return load_config_from_db()


def load_net_values():
    data = load_net_value_history()
    if not data:
        return {}
    result = {}
    for code, dates in data.items():
        if dates:
            latest_date = max(dates.keys())
            result[code] = dates[latest_date]
    return result


def _decode_name(name):
    """尝试修复可能的中文编码问题"""
    if not name or not isinstance(name, str):
        return name or ""
    try:
        if "\\u" in repr(name):
            return name.encode("latin-1").decode("unicode-escape")
    except Exception:
        pass
    return name


# ============================================================
# 资产计算
# ============================================================
def calculate_category_value(config, net_values):
    """计算各类别市值"""
    category_values = {}
    for category, funds in config["funds"].items():
        total = 0
        for fund in funds:
            if fund["code"] in net_values:
                total += fund["shares"] * net_values[fund["code"]]["net_value"]
        category_values[category] = round(total, 2)
    return category_values


def calculate_current_weights(config, net_values):
    """计算当前各类别权重（百分比）"""
    category_values = calculate_category_value(config, net_values)
    total = sum(category_values.values())
    if total == 0:
        return {"nasdaq": 0, "dividend": 0, "gold": 0}
    return {k: round(v / total * 100, 1) for k, v in category_values.items()}


def calculate_category_profit(config, net_values):
    """计算各类别成本/市值/收益"""
    result = {}
    for category in ["nasdaq", "dividend", "gold"]:
        cost = 0
        market = 0
        for fund in config["funds"].get(category, []):
            if fund["code"] in net_values:
                cost += fund["shares"] * fund.get("cost_price", 0)
                market += fund["shares"] * net_values[fund["code"]]["net_value"]
        result[category] = {
            "cost": round(cost, 2),
            "market": round(market, 2),
            "profit": round(market - cost, 2),
            "profit_pct": round((market - cost) / cost * 100, 2) if cost > 0 else 0,
        }
    return result


# ============================================================
# V2 估值评分系统接入
# ============================================================
def get_valuation_data():
    """
    获取 V2 估值评分系统的数据
    返回：(overview, portfolio_suggestion) 或 (None, None)
    """
    try:
        from services.valuation_scoring import get_valuation_overview, get_portfolio_suggestion
        overview = get_valuation_overview()
        suggestion = get_portfolio_suggestion(1000.0)  # 以1000元为例计算比例
        return overview, suggestion
    except Exception as e:
        print(f"[日报] 估值评分数据获取失败: {e}")
        return None, None


# ============================================================
# 持仓明细数据
# ============================================================
def build_holdings_detail(config, net_values):
    """整理持仓明细"""
    holdings = []
    pending_total = 0
    for category, funds in config["funds"].items():
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                shares = fund["shares"]
                cost_price = fund.get("cost_price", 0)
                market_value = round(shares * nv["net_value"], 2)
                cost_value = round(shares * cost_price, 2)
                profit = round(market_value - cost_value, 2)
                profit_pct = round(profit / cost_value * 100, 2) if cost_value > 0 else 0
                pending_orders = fund.get("pending_orders", [])
                pending = round(sum(o.get("amount", 0) for o in pending_orders), 2)
                pending_total += pending
                holdings.append({
                    "name": _decode_name(fund.get("name", fund["code"])),
                    "code": fund["code"],
                    "category": category,
                    "shares": shares,
                    "net_value": nv["net_value"],
                    "cost_price": cost_price,
                    "market_value": market_value,
                    "profit": profit,
                    "profit_pct": profit_pct,
                    "change": round(nv.get("change", 0), 2),
                    "pending": pending,
                })
    return holdings, round(pending_total, 2)


# ============================================================
# 简单报告生成（无需 API Key）
# ============================================================
CATEGORY_LABELS = {
    "nasdaq": "纳斯达克",
    "dividend": "红利低波",
    "gold": "黄金",
}


def _score_band_label(score):
    """根据评分返回买卖区间标签"""
    if score < 30:
        return "🟢 极度低估 · 加仓"
    if score < 50:
        return "🟢 低估 · 超配"
    if score < 65:
        return "🟡 正常 · 持有"
    if score < 80:
        return "🟠 偏高 · 减配"
    return "🔴 高估 · 止盈"


def generate_simple_report():
    """
    生成结构化的每日投资报告（无需 API key）
    集成 V2 估值评分系统：估值评分 / 便宜度排名 / 组合配置建议 / 宏观因子
    """
    today = datetime.now().strftime("%Y-%m-%d")
    config = load_config()
    net_values = load_net_values()

    # ---- 资产计算 ----
    category_values = calculate_category_value(config, net_values)
    current_weights = calculate_current_weights(config, net_values)
    category_profit = calculate_category_profit(config, net_values)
    total_value = round(sum(category_values.values()), 2)
    total_cost = round(sum(v["cost"] for v in category_profit.values()), 2)
    total_profit = round(total_value - total_cost, 2)
    total_profit_pct = round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0

    # ---- 持仓明细 ----
    holdings, pending_total = build_holdings_detail(config, net_values)

    # ---- 目标配置 ----
    targets = config.get("targets", {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2})
    target_pct = {k: round(v * 100, 0) for k, v in targets.items()}

    # ---- V2 估值评分数据 ----
    valuation_overview, portfolio_suggestion = get_valuation_data()

    # ============================================================
    # 开始组装报告
    # ============================================================
    lines = []

    # ---- 头部 ----
    lines.append(f"# 📊 基金投资日报 · {today}")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**数据来源**: 天天基金 / AkShare（净值）· FMP / 中证指数（估值）")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ============================================================
    # 第一部分：资产总览
    # ============================================================
    lines.append("## 💰 资产总览")
    lines.append("")
    lines.append("| 项目 | 金额 |")
    lines.append("|------|------|")
    lines.append(f"| **总资产市值** | ¥{total_value:,.2f} |")
    lines.append(f"| 总投入成本 | ¥{total_cost:,.2f} |")
    lines.append(f"| **总盈亏** | **¥{total_profit:+,.2f} ({total_profit_pct:+,.2f}%)** |")
    lines.append(f"| 待确认金额 | ¥{pending_total:,.2f} |")
    lines.append("")

    # ============================================================
    # 第二部分：资产配置健康度
    # ============================================================
    lines.append("## ⚖️ 资产配置健康度")
    lines.append("")
    lines.append("| 资产类别 | 市值 | 当前占比 | 目标占比 | 偏离度 | 收益 |")
    lines.append("|---------|------|---------|---------|--------|------|")
    for cat in ["nasdaq", "dividend", "gold"]:
        label = CATEGORY_LABELS.get(cat, cat)
        mv = category_values.get(cat, 0)
        cur_w = current_weights.get(cat, 0)
        tgt_w = target_pct.get(cat, 0)
        dev = cur_w - tgt_w
        prof = category_profit.get(cat, {}).get("profit", 0)
        dev_icon = "🔴" if abs(dev) > 5 else ("🟡" if abs(dev) > 2 else "✅")
        lines.append(
            f"| **{label}** | ¥{mv:,.2f} | {cur_w:.1f}% | {tgt_w:.0f}% | "
            f"{dev_icon} {dev:+.1f}% | ¥{prof:+,.2f} |"
        )
    lines.append("")

    # ============================================================
    # 第三部分：V2 估值评分（核心新增）
    # ============================================================
    if valuation_overview and "assets" in valuation_overview:
        assets_data = valuation_overview["assets"]

        # ---- 防御性处理：过滤无有效评分的资产 ----
        def _safe_score(asset):
            """从资产数据中安全获取评分，None 视为 999（昂贵）"""
            if not asset:
                return 999
            s = asset.get("score")
            if s is None:
                return 999
            try:
                return float(s)
            except (TypeError, ValueError):
                return 999

        valid_cats = [c for c in assets_data.keys() if _safe_score(assets_data[c]) < 999]

        if valid_cats:
            lines.append("## 🎯 V2 估值评分（0便宜 / 100昂贵）")
            lines.append("")
            lines.append("> 基于成分股加权估值 × 宏观修正因子计算，分数越低表示资产越便宜。")
            lines.append("")

            # 按分数从低到高排序（便宜在前）
            sorted_cats = sorted(valid_cats, key=lambda k: _safe_score(assets_data[k]))

            # ---- 3.1 评分卡片表 ----
            lines.append("### · 三大资产估值评分")
            lines.append("")
            lines.append("| 资产类别 | 估值分 | 买卖区间 | 建议定投倍数 | 数据质量 |")
            lines.append("|---------|--------|---------|-------------|----------|")

            for cat in sorted_cats:
                asset = assets_data[cat]
                score = _safe_score(asset)
                band = asset.get("band") or "正常"
                mult = asset.get("invest_multiplier") or 1.0
                reliability = asset.get("reliability") or "fallback"
                reliability_label = {
                    "full": "完整（百分位）",
                    "limited": "有限",
                    "fallback": "常识区间",
                    "no_data": "无数据",
                }.get(reliability, reliability)

                # 给分数着色（越便宜越绿）
                if score < 30:
                    score_str = f"**🟢 {int(score)}**"
                elif score < 50:
                    score_str = f"🟢 {int(score)}"
                elif score < 65:
                    score_str = f"🟡 {int(score)}"
                elif score < 80:
                    score_str = f"🟠 {int(score)}"
                else:
                    score_str = f"**🔴 {int(score)}**"

                lines.append(
                    f"| {CATEGORY_LABELS.get(cat, cat)} | {score_str} | {band} | "
                    f"×{mult:.2f} | {reliability_label} |"
                )
            lines.append("")

            # ---- 3.2 便宜度排名 ----
            lines.append("### · 资产便宜度排名")
            lines.append("")
            for rank, cat in enumerate(sorted_cats, 1):
                asset = assets_data[cat]
                score = _safe_score(asset)
                band = asset.get("band") or "正常"
                lines.append(f"**{rank}. {CATEGORY_LABELS.get(cat, cat)}** — 估值分 {int(score)}，{band}")
            lines.append("")

            # ---- 3.3 估值指标明细 ----
            lines.append("### · 关键估值指标明细")
            lines.append("")
            lines.append("| 资产 | 指标明细 | 宏观修正 |")
            lines.append("|------|---------|----------|")
            for cat in sorted_cats:
                asset = assets_data[cat]
                metric_scores = []
                for m in asset.get("metrics", []):
                    label = m.get("label") or "未知"
                    score_val = m.get("score")
                    if score_val is not None:
                        metric_scores.append(f"{label}:{int(score_val)}")
                metric_str = " / ".join(metric_scores) if metric_scores else "—"
                macro = asset.get("macro_factor") or 1.0
                lines.append(f"| {CATEGORY_LABELS.get(cat, cat)} | {metric_str} | ×{macro:.2f} |")
            lines.append("")

            # ---- 3.4 宏观因子影响 ----
            macro_details = []
            for cat in sorted_cats:
                details = assets_data[cat].get("macro_details", [])
                if details:
                    macro_details.extend(details)

            if macro_details:
                lines.append("### · 宏观因子影响")
                lines.append("")
                lines.append("| 宏观指标 | 当前值 | 影响方向 |")
                lines.append("|---------|-------|---------|")
                seen = set()
                for md in macro_details:
                    key = f"{md.get('label','')}|{md.get('current','')}"
                    if key in seen:
                        continue
                    seen.add(key)
                    label = md.get("label") or "未知"
                    current = md.get("current") or "—"
                    impact = md.get("impact") or "—"
                    lines.append(f"| {label} | {current} | {impact} |")
                lines.append("")

    # ============================================================
    # 第四部分：组合配置建议（核心新增）
    # ============================================================
    if portfolio_suggestion:
        valid_suggestions = []
        for s in portfolio_suggestion:
            try:
                amount = float(s.get("amount") or 0)
                ratio = float(s.get("ratio") or 0)
                mult = float(s.get("multiplier") or 1.0)
                score_val = s.get("score")
                score_int = int(float(score_val)) if score_val is not None else 0
                if amount > 0 or ratio > 0:
                    valid_suggestions.append({
                        "label": CATEGORY_LABELS.get(s.get("asset", ""), s.get("label", "")),
                        "amount": amount,
                        "ratio": ratio,
                        "multiplier": mult,
                        "score": score_int,
                    })
            except (TypeError, ValueError):
                continue

        if valid_suggestions:
            lines.append("## 📋 组合配置建议（基于估值评分）")
            lines.append("")
            lines.append("> 越便宜的资产，定投倍数越高；按估值评分动态分配金额。")
            lines.append("")

            total_alloc = sum(s["amount"] for s in valid_suggestions)
            lines.append("| 资产类别 | 建议金额 | 占比 | 定投倍数 | 估值分 |")
            lines.append("|---------|---------|------|---------|--------|")
            for s in valid_suggestions:
                lines.append(
                    f"| **{s['label']}** | ¥{s['amount']:.0f} | {s['ratio']:.0f}% | ×{s['multiplier']:.2f} | {s['score']} |"
                )
            lines.append("")
            lines.append(f"> 以 ¥{total_alloc:.0f} 为例的分配建议，实际可按您的定投基数等比例缩放。")
            lines.append("")

    # ============================================================
    # 第五部分：持仓明细
    # ============================================================
    lines.append("## 📑 持仓明细")
    lines.append("")

    for category in ["nasdaq", "dividend", "gold"]:
        cat_funds = [h for h in holdings if h["category"] == category]
        if not cat_funds:
            continue
        cat_label = CATEGORY_LABELS.get(category, category)
        cat_total = sum(h["market_value"] for h in cat_funds)
        lines.append(f"### {cat_label}（市值 ¥{cat_total:,.2f}）")
        lines.append("")
        lines.append("| 基金 | 代码 | 份额 | 净值 | 市值 | 成本 | 盈亏 | 日涨跌 |")
        lines.append("|------|------|------|------|------|------|------|--------|")

        # 按市值从大到小排序
        cat_funds.sort(key=lambda h: h["market_value"], reverse=True)
        for h in cat_funds:
            pending_str = f" (待确认:¥{h['pending']:.0f})" if h["pending"] > 0 else ""
            profit_color = "🟢" if h["profit"] >= 0 else "🔴"
            change_color = "🟢" if h["change"] >= 0 else "🔴"
            lines.append(
                f"| {h['name']}{pending_str} | {h['code']} | {h['shares']:.2f} | "
                f"{h['net_value']:.4f} | ¥{h['market_value']:,.2f} | "
                f"¥{h['cost_price'] * h['shares']:,.2f} | "
                f"{profit_color} ¥{h['profit']:+,.2f} ({h['profit_pct']:+,.2f}%) | "
                f"{change_color} {h['change']:+,.2f}% |"
            )
        lines.append("")

    # ============================================================
    # 第六部分：再平衡与操作建议
    # ============================================================
    lines.append("## 🎯 再平衡与操作建议")
    lines.append("")

    # 计算偏离度并给出建议
    dev_messages = []
    for cat in ["nasdaq", "dividend", "gold"]:
        dev = current_weights.get(cat, 0) - target_pct.get(cat, 0)
        label = CATEGORY_LABELS.get(cat, cat)
        if dev > 3:
            dev_messages.append(f"🔴 **{label}超配 +{dev:.1f}%**：建议暂停或减少此板块的定投，将资金转向低配资产")
        elif dev < -3:
            dev_messages.append(f"🟢 **{label}低配 {dev:.1f}%**：建议增加此板块的定投金额，优先补仓")
        else:
            dev_messages.append(f"✅ **{label}正常 {dev:+.1f}%**：与目标配置接近，维持常规定投")

    for msg in dev_messages:
        lines.append(f"- {msg}")
    lines.append("")

    # 基于估值评分的操作建议
    if valuation_overview and "assets" in valuation_overview:
        assets_data = valuation_overview["assets"]

        def _safe_score2(asset):
            if not asset:
                return None
            s = asset.get("score")
            if s is None:
                return None
            try:
                return float(s)
            except (TypeError, ValueError):
                return None

        valid_for_tips = [(c, _safe_score2(assets_data[c])) for c in assets_data.keys()]
        valid_for_tips = [(c, s) for c, s in valid_for_tips if s is not None]

        if valid_for_tips:
            lines.append("### · 基于估值评分的操作提示")
            lines.append("")
            sorted_by_score = sorted(valid_for_tips, key=lambda x: x[1])
            cheapest_cat, cheapest_score = sorted_by_score[0]
            cheapest_label = CATEGORY_LABELS.get(cheapest_cat, cheapest_cat)

            if cheapest_score < 50:
                lines.append(f"- 🟢 **当前最划算：{cheapest_label}（估值分 {int(cheapest_score)}）**：建议优先加仓，提高定投倍数")
            elif cheapest_score < 65:
                lines.append(f"- 🟡 **估值中性：{cheapest_label}（估值分 {int(cheapest_score)}）**：按目标比例正常定投")
            else:
                lines.append(f"- 🔴 **整体偏高**：建议降低整体定投金额，或增加现金储备")

            # 检查是否有高估资产
            for cat, score in sorted_by_score:
                if score >= 75:
                    label = CATEGORY_LABELS.get(cat, cat)
                    lines.append(f"- 🟠 **{label}偏高（估值分 {int(score)}）**：建议减配，至少不新增资金")
            lines.append("")

    # ============================================================
    # 第七部分：风险提示与免责声明
    # ============================================================
    lines.append("## ⚠️ 风险提示")
    lines.append("")
    lines.append("- **估值评分参考性**：估值评分基于历史数据和常识区间，不构成买卖信号，仅作为资产配置的辅助参考")
    lines.append("- **市场波动风险**：纳斯达克等权益类资产波动较大，请做好长期持有的准备")
    lines.append("- **宏观不确定性**：利率、汇率、地缘政治等因素可能显著影响资产估值")
    lines.append("- **基金跟踪误差**：QDII基金存在汇率风险和跟踪误差，实际收益与指数可能有偏差")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> **免责声明**：本报告由 AI 基于您的持仓数据和公开市场数据自动生成，仅供投资决策参考，不构成任何投资承诺或收益保证。市场有风险，投资需谨慎。")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# AI 增强版报告（有 API Key 时使用）
# ============================================================
def generate_daily_report(api_key=None):
    """生成每日报告（优先使用 API，无 API 时调用简单报告）"""
    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY")

    if not api_key:
        print("[日报] 未配置 API Key，使用结构化模板生成")
        return generate_simple_report()

    # ---- 获取原始数据 ----
    today = datetime.now().strftime("%Y-%m-%d")
    config = load_config()
    net_values = load_net_values()

    category_values = calculate_category_value(config, net_values)
    current_weights = calculate_current_weights(config, net_values)
    category_profit = calculate_category_profit(config, net_values)
    total_value = round(sum(category_values.values()), 2)
    total_cost = round(sum(v["cost"] for v in category_profit.values()), 2)
    total_profit = round(total_value - total_cost, 2)
    total_profit_pct = round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0

    holdings, pending_total = build_holdings_detail(config, net_values)
    targets = config.get("targets", {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2})
    target_pct = {k: round(v * 100, 0) for k, v in targets.items()}

    # ---- V2 估值评分数据 ----
    valuation_overview, portfolio_suggestion = get_valuation_data()

    # ---- 简化持仓明细（避免 Prompt 过长）----
    # 只保留市值 > 200 的基金（忽略小额仓位），按市值排序
    significant_holdings = [h for h in holdings if h["market_value"] > 200]
    significant_holdings.sort(key=lambda h: h["market_value"], reverse=True)

    holdings_summary = []
    for h in significant_holdings:
        cat_label = CATEGORY_LABELS.get(h["category"], h["category"])
        holdings_summary.append(
            f"- [{cat_label}] {h['name']}({h['code']}): "
            f"市值¥{h['market_value']:,.0f}, "
            f"盈亏¥{h['profit']:+,.0f}({h['profit_pct']:+,.1f}%), "
            f"日涨跌{h['change']:+,.2f}%"
        )

    holdings_text = "\n".join(holdings_summary)

    # ---- 估值评分数据整理 ----
    valuation_text = ""
    if valuation_overview and "assets" in valuation_overview:
        valuation_text_parts = []
        assets_data = valuation_overview["assets"]

        def _safe_score3(asset):
            if not asset:
                return None
            s = asset.get("score")
            if s is None:
                return None
            try:
                return float(s)
            except (TypeError, ValueError):
                return None

        valid_for_prompt = [(c, _safe_score3(assets_data[c])) for c in assets_data.keys()]
        valid_for_prompt = [(c, s) for c, s in valid_for_prompt if s is not None]
        valid_for_prompt.sort(key=lambda x: x[1])

        for cat, score in valid_for_prompt:
            asset = assets_data[cat]
            label = CATEGORY_LABELS.get(cat, cat)
            band = asset.get("band") or "正常"
            mult = asset.get("invest_multiplier") or 1.0
            reliability = asset.get("reliability") or "limited"
            valuation_text_parts.append(
                f"- {label}: 估值分{int(score)}(0便宜/100昂贵), {band}, 建议定投倍数×{mult:.2f}, 数据质量:{reliability}"
            )
        valuation_text = "\n".join(valuation_text_parts)

    # ---- 组合建议整理 ----
    suggestion_text = ""
    if portfolio_suggestion:
        suggestion_parts = []
        for s in portfolio_suggestion:
            label = CATEGORY_LABELS.get(s.get("asset", ""), s.get("label", ""))
            try:
                amount = float(s.get("amount") or 0)
                ratio = float(s.get("ratio") or 0)
                mult = float(s.get("multiplier") or 1.0)
                score_val = s.get("score")
                score_int = int(float(score_val)) if score_val is not None else 0
                if amount > 0 or ratio > 0:
                    suggestion_parts.append(
                        f"- {label}: 建议¥{amount:.0f}(占比{ratio:.0f}%), 定投倍数×{mult:.2f}, 估值分{score_int}"
                    )
            except (TypeError, ValueError):
                continue
        suggestion_text = "\n".join(suggestion_parts)

    # ---- 调用 DeepSeek ----
    print("[日报] 使用 DeepSeek API 生成增强版报告...")

    try:
        from openai import OpenAI
    except ImportError:
        print("[日报] openai 库未安装，回退到结构化模板报告")
        return generate_simple_report()

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    # ---- System Prompt：为当前项目量身定制 ----
    system_prompt = """你是一位专业的基金投资顾问，服务于一个以"纳斯达克+红利低波+黄金"三资产平衡策略为核心的定投项目。

你的核心定位：
1. **价值导向**：关注估值便宜度而非短期热点
2. **纪律优先**：强调按目标比例再平衡，反对情绪驱动的操作
3. **长期主义**：所有建议应基于3-5年的投资周期评估

报告撰写要求：
- 使用中文，Markdown 格式（# 一级标题 / ## 二级标题 / 表格用 | 分隔）
- 风格专业、克制、数据驱动，避免情绪化语言
- 所有判断必须有数据支撑（引用下方提供的数据）
- 对"估值评分"的解读要谨慎：它是辅助参考，不是买卖信号
- 对偏离度 > 5% 的资产必须明确给出操作方向（加仓/减配/维持）
- 结尾必须有风险提示和免责声明
"""

    # ---- User Prompt：结构化数据 + 明确任务 ----
    user_prompt = f"""请基于以下真实持仓和估值数据，生成一份 {today} 的基金投资日报。

---

【一、基本数据】
- 报告日期: {today}
- 总资产市值: ¥{total_value:,.2f}
- 总投入成本: ¥{total_cost:,.2f}
- 总盈亏: ¥{total_profit:+,.2f} ({total_profit_pct:+,.2f}%)
- 待确认金额: ¥{pending_total:,.2f}

【二、资产配置】
| 资产类别 | 市值 | 当前占比 | 目标占比 | 偏离度 | 收益 |
|---------|------|---------|---------|--------|------|
| 纳斯达克 | ¥{category_values.get('nasdaq', 0):,.2f} | {current_weights.get('nasdaq', 0):.1f}% | {target_pct.get('nasdaq', 0):.0f}% | {current_weights.get('nasdaq', 0) - target_pct.get('nasdaq', 0):+.1f}% | ¥{category_profit.get('nasdaq', {}).get('profit', 0):+,.2f} |
| 红利低波 | ¥{category_values.get('dividend', 0):,.2f} | {current_weights.get('dividend', 0):.1f}% | {target_pct.get('dividend', 0):.0f}% | {current_weights.get('dividend', 0) - target_pct.get('dividend', 0):+.1f}% | ¥{category_profit.get('dividend', {}).get('profit', 0):+,.2f} |
| 黄金 | ¥{category_values.get('gold', 0):,.2f} | {current_weights.get('gold', 0):.1f}% | {target_pct.get('gold', 0):.0f}% | {current_weights.get('gold', 0) - target_pct.get('gold', 0):+.1f}% | ¥{category_profit.get('gold', {}).get('profit', 0):+,.2f} |

【三、V2 估值评分（核心参考）】
评分范围 0-100，分数越低越便宜。以下是三大资产的当前评分：
{valuation_text if valuation_text else "（暂无估值评分数据）"}

【四、组合配置建议（基于估值评分）】
以下是按估值评分计算的 ¥1000 示例分配（实际投资按您的定投基数等比例缩放）：
{suggestion_text if suggestion_text else "（暂无组合建议）"}

【五、持仓明细（市值>¥200）】
{holdings_text if holdings_text else "（无持仓数据）"}

---

请按以下结构生成报告，每一部分都需要有实际数据支撑，不要泛泛而谈：

## 一、资产总览
- 用一个简洁的表格展示总资产、总盈亏、待确认金额

## 二、资产配置健康度
- 用表格展示三大资产的配置偏离情况
- 对偏离度超过 ±3% 的资产给出明确的诊断（超配/低配）

## 三、V2 估值评分解读
- 解读三大资产当前的估值便宜度
- 指出哪类资产当前最具性价比，哪类偏高
- 结合估值评分给出整体的仓位管理建议

## 四、组合配置建议
- 基于估值评分和配置偏离度，给出具体的定投金额分配建议
- 对每类资产给出操作方向（加仓/维持/减配）

## 五、持仓明细摘要
- 用表格列出主要持仓（市值排序），重点标注盈利和日涨跌

## 六、风险提示
- 结合当前估值水平和配置偏离度，给出 3-5 条具体的风险提示

请用中文，Markdown 格式，风格专业克制。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
            timeout=60,
        )

        report = response.choices[0].message.content
        if report and report.strip():
            print("[日报] DeepSeek 报告生成成功")
            return report

    except Exception as e:
        print(f"[日报] DeepSeek API 调用失败: {e}")
        traceback.print_exc()

    # ---- API 失败时回退到结构化模板 ----
    print("[日报] 回退到结构化模板报告")
    return generate_simple_report()


# ============================================================
# 报告保存 / 发送
# ============================================================
def decode_unicode_text(text):
    """尝试修复可能的 Unicode 编码问题"""
    if not text or not isinstance(text, str):
        return text or ""
    if "\\u" in repr(text):
        try:
            return text.encode("latin-1").decode("unicode-escape")
        except Exception:
            pass
    return text


def save_report(report_content):
    """保存报告到 reports/ 目录"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)

    report_content = decode_unicode_text(report_content)

    filename = os.path.join(report_dir, f"daily_report_{today}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 基金投资日报\n\n")
        f.write(f"**生成日期**: {today}\n\n")
        f.write(f"---\n\n")
        f.write(report_content)

    print(f"[日报] 报告已保存: {filename}")
    return filename


def _split_content(text, max_len=900):
    """将长文本按段落拆分为多个片段，每个片段不超过 max_len 字符"""
    segments = []
    # 优先按双换行（段落）拆分
    paragraphs = text.split("\n\n")
    current = ""
    for para in paragraphs:
        # 如果单个段落就超过限制，按行拆分
        if len(para) > max_len:
            # 先把 current 存起来
            if current:
                segments.append(current.strip())
                current = ""
            # 按行拆分长段落
            lines = para.split("\n")
            for line in lines:
                if len(current) + len(line) + 1 > max_len:
                    if current:
                        segments.append(current.strip())
                    current = line
                else:
                    current = (current + "\n" + line) if current else line
        elif len(current) + len(para) + 2 > max_len:
            if current:
                segments.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para) if current else para
    if current:
        segments.append(current.strip())
    return segments


def send_to_feishu(report_content, webhook_url):
    """发送报告到飞书机器人（超长自动分段发送，每段不超过1000字）"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_content = decode_unicode_text(report_content)

    # 拆分为多个片段（留足标题前缀空间）
    segments = _split_content(report_content, max_len=900)
    total = len(segments)
    header = f"【{today} 基金投资日报】"

    def _send(text):
        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
        try:
            resp = requests.post(
                webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload, ensure_ascii=False),
                timeout=15,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    return True
                print(f"[日报] 飞书发送失败: {result.get('msg', '未知错误')}")
            else:
                print(f"[日报] 飞书发送失败，HTTP状态码: {resp.status_code}")
        except Exception as e:
            print(f"[日报] 发送到飞书失败: {e}")
        return False

    if total == 1:
        # 一段就能装下
        ok = _send(f"{header}\n\n{segments[0]}")
        if ok:
            print("[日报] 已发送到飞书")
        return ok

    # 多段发送
    all_ok = True
    for i, seg in enumerate(segments, 1):
        if i == 1:
            text = f"{header} ({i}/{total})\n\n{seg}"
        else:
            text = f"{header} ({i}/{total}) 续\n\n{seg}"
        ok = _send(text)
        if not ok:
            all_ok = False
            print(f"[日报] 第 {i}/{total} 段发送失败")
        import time
        time.sleep(2.0)  # 避免触发飞书频率限制

    if all_ok:
        print(f"[日报] 已发送到飞书（共 {total} 段）")
    return all_ok


# ============================================================
# 命令行入口
# ============================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(description="每日报告生成器")
    parser.add_argument("--api-key", "-k", help="DeepSeek API Key")
    parser.add_argument("--feishu-webhook", "-f", help="飞书机器人 Webhook 地址")
    args = parser.parse_args()

    print("=== 基金投资日报生成器 ===")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    report = generate_daily_report(api_key=args.api_key)

    if report:
        print("\n=== 报告预览（前 500 字）===")
        print(report[:500] + "\n...")
        print("=" * 50)
        save_report(report)

        if args.feishu_webhook:
            send_to_feishu(report, args.feishu_webhook)
    else:
        print("[日报] 报告生成失败")


if __name__ == "__main__":
    main()
