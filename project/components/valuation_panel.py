"""
V2 估值面板组件
=====================

展示三大类资产的估值评分、分位线图、智能定投倍数建议、组合建议。
适配 V2 评分系统：
  - 三大资产统一 0-100 分
  - 每指标显示可信赖度（full/limited/fallback）
  - 宏观修正因子展示
  - 资产排名 + 组合建议
"""

import logging
from datetime import datetime

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from services.valuation_fetcher import (
    fetch_all_valuations,
    fetch_danjuan_valuation,
    fetch_fred_metrics,
    fetch_gold_price_from_fmp,
    get_api_key,
    set_api_key,
)
from services.valuation_scoring import (
    get_valuation_overview,
    get_portfolio_suggestion,
    get_auto_invest_multiplier,
    ASSET_LABELS,
    METRIC_META,
    MACRO_META,
)
from services.database import get_valuation_history

logger = logging.getLogger(__name__)

ASSET_NAMES = ASSET_LABELS

RELIABILITY_LABEL = {
    "full": ("✅", "full", "历史数据充足(60+天)，使用百分位评分"),
    "limited": ("⚠️", "limited", "历史数据有限(30-59天)，百分位评分仅供参考"),
    "fallback": ("🧪", "fallback", "历史数据不足(<30天)，使用常识区间估算"),
    "no_data": ("❌", "no_data", "无当前数据"),
}


def _score_color(score):
    if score is None:
        return "#9e9e9e"
    if score < 20:
        return "#00b050"
    if score < 40:
        return "#70ad47"
    if score < 60:
        return "#ffc000"
    if score < 80:
        return "#ed7d31"
    return "#c00000"


def _score_emoji(score):
    if score is None:
        return "❔"
    if score < 20:
        return "🟢"
    if score < 40:
        return "🟩"
    if score < 60:
        return "🟡"
    if score < 80:
        return "🟧"
    return "🔴"


def _format_val(v, unit=""):
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}{unit}"
    except Exception:
        return "—"


def _reliability_badge(rel):
    emoji, label, _ = RELIABILITY_LABEL.get(rel, ("?", rel, ""))
    return f"{emoji} `{label}`"


# ==================================================================
# 估值大卡（单个资产）
# ==================================================================

def _render_asset_card(asset_key, asset_result):
    asset_name = ASSET_NAMES.get(asset_key, asset_key)
    score = asset_result["score"]
    base_score = asset_result.get("base_score")
    macro_factor = asset_result.get("macro_factor")
    band = asset_result.get("band")
    rec = asset_result.get("recommendation")
    mult = asset_result.get("invest_multiplier", 1.0)
    color = _score_color(score)
    emoji = _score_emoji(score)

    st.markdown(f"#### {emoji} **{asset_name}** · <span style='color:{color}'>{band}</span>",
                unsafe_allow_html=True)

    col1, col2 = st.columns([1, 2])
    with col1:
        # 圆环
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=score if score is not None else 0,
            domain={'x': [0, 1], 'y': [0, 1]},
            gauge={
                'axis': {'range': [0, 100], 'tickvals': [0, 20, 40, 60, 80, 100]},
                'steps': [
                    {'range': [0, 20], 'color': "#00b050"},
                    {'range': [20, 40], 'color': "#70ad47"},
                    {'range': [40, 60], 'color': "#ffc000"},
                    {'range': [60, 80], 'color': "#ed7d31"},
                    {'range': [80, 100], 'color': "#c00000"},
                ],
                'threshold': {'line': {'color': "black", 'width': 3},
                               'thickness': 0.85,
                               'value': score if score is not None else 0},
                'bar': {'color': color, 'thickness': 0.5},
            },
            number={'font': {'size': 22}},
            title={'text': "0便宜 / 100贵"},
        ))
        fig.update_layout(height=210, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width='stretch', key=f"gauge-{asset_key}")

    with col2:
        # 摘要信息
        info_lines = []
        if score is not None:
            info_lines.append(f"**💡 建议：<span style='color:{color}'>{rec}</span>**")
            info_lines.append(f"**💰 定投倍数：<span style='color:{color}'>{mult:.1f}x</span>**")
        else:
            info_lines.append("**💡 暂无估值数据（请先刷新数据）**")

        if base_score is not None and macro_factor is not None and abs(macro_factor - 1.0) > 0.001:
            arrow = "↑" if macro_factor > 1.0 else "↓"
            diff = (macro_factor - 1.0) * 100
            info_lines.append(f"🌐 基准分 {base_score:.1f} × 宏观修正 {arrow}{abs(diff):.0f}% → 最终 {score:.1f}")
        elif base_score is not None:
            info_lines.append(f"🌐 基准分 {base_score:.1f}（无有效宏观数据）")

        for line in info_lines:
            st.markdown(line, unsafe_allow_html=True)

        # 指标详情表
        rows = []
        for m in asset_result.get("metrics", []):
            cur = m.get("current")
            pct = m.get("percentile")  # 已经是百分比数值
            s = m.get("score")
            label = m.get("label")
            rel = m.get("reliability", "no_data")
            data_date = m.get("data_date") or "—"
            r_emoji, r_label, _ = RELIABILITY_LABEL.get(rel, ("?", rel, ""))

            pct_str = f"{pct:.0f}%" if pct is not None else "—"
            score_str = f"{s:.0f}" if s is not None else "—"

            rows.append({
                "指标": f"{r_emoji} {label}",
                "当前值": _format_val(cur),
                "数据日期": data_date,
                "百分位": pct_str,
                "评分": score_str,
                "方法": r_label,
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True, height=180)
        else:
            st.info("暂无指标数据")

        # 宏观修正明细（如果有）
        macro_details = asset_result.get("macro_details", [])
        if macro_details:
            with st.expander(f"🌐 宏观因子影响（{len(macro_details)}项）", expanded=False):
                macro_rows = []
                for md in macro_details:
                    macro_rows.append({
                        "因子": md["label"],
                        "当前值": _format_val(md["value"]),
                        "数据日期": md.get("data_date") or "—",
                        "压力": f"{md['pressure']} ({md['pressure_score']:.0f})",
                        "权重": f"{md['weight']:.1f}",
                    })
                st.dataframe(pd.DataFrame(macro_rows), width='stretch', hide_index=True)

    st.divider()


# ==================================================================
# 分位线图（指标历史曲线 + 当前分位线）
# ==================================================================

def _render_metric_chart(asset_type, metric_name, metric_label):
    history = get_valuation_history(asset_type, metric_name)
    if not history:
        st.info(f"{metric_label}：暂无历史数据")
        return
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("date")

    if len(df) < 5:
        st.info(f"{metric_label}：历史数据仅 {len(df)} 点，不足画图")
        # 但至少显示最新值
        latest = df.iloc[-1]
        st.metric(f"{metric_label} 最新", f"{float(latest['value']):.3f}",
                  delta=str(latest["date"].date()))
        return

    current = float(df["value"].iloc[-1])
    vals = df["value"].values
    p20 = float(pd.Series(vals).quantile(0.2))
    p50 = float(pd.Series(vals).quantile(0.5))
    p80 = float(pd.Series(vals).quantile(0.8))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"], mode="lines",
        name=metric_label,
        line=dict(color="#2a5298", width=2),
        fill="tozeroy",
        fillcolor="rgba(42,82,152,0.1)",
    ))
    fig.add_hline(y=p80, line_dash="dash", line_color="#c00000",
                  annotation_text=f"80%分位: {p80:.3f}",
                  annotation_position="top right")
    fig.add_hline(y=p50, line_dash="dash", line_color="#ffc000",
                  annotation_text=f"中位: {p50:.3f}",
                  annotation_position="top right")
    fig.add_hline(y=p20, line_dash="dash", line_color="#00b050",
                  annotation_text=f"20%分位: {p20:.3f}",
                  annotation_position="bottom right")
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[-1]], y=[current],
        mode="markers", marker=dict(size=12, color="red", symbol="diamond"),
        name=f"当前: {current:.3f}",
    ))
    fig.update_layout(
        height=260, margin=dict(l=10, r=10, t=30, b=10),
        title=f"{metric_label} 历史走势 ({len(df)}天)",
        showlegend=False,
    )
    st.plotly_chart(fig, width='stretch', key=f"chart-{asset_type}-{metric_name}")


# ==================================================================
# API Key 配置
# ==================================================================

def _render_api_key_config():
    with st.expander("🔑 API Key 配置（FMP / FRED）", expanded=False):
        fmp = get_api_key("fmp") or ""
        fred = get_api_key("fred") or ""

        new_fmp = st.text_input("FMP (FinancialModelingPrep) API Key",
                                 value=fmp, type="password",
                                 help="免费版每天 250 次请求，用于获取黄金/白银价格")
        new_fred = st.text_input("FRED (圣路易斯联邦储备银行) API Key",
                                   value=fred, type="password",
                                   help="完全免费，用于获取利率、VIX、美元指数等宏观数据")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("保存 API Keys", width='stretch'):
                set_api_key("fmp", new_fmp.strip())
                set_api_key("fred", new_fred.strip())
                st.success("已保存！")
        with c2:
            st.markdown("**数据来源说明：**\n- 纳指100 / 中证红利 PE·PB·PEG·股息率 → 蛋卷基金(官方, 10年历史)\n- 黄金白银价格 → FMP GCUSD/SIUSD\n- 宏观指标 → FRED")


# ==================================================================
# 主渲染
# ==================================================================

def render_valuation_panel():
    st.header("📊 估值评分系统")
    st.markdown(
        "三层架构：**成分股估值（蛋卷官方指数估值）** × **宏观修正** → "
        "**跨资产统一 0-100 分评分**。分数越低越便宜，定投倍数越高。"
    )

    # 操作按钮
    st.markdown("**⚡ 数据操作**")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🔄 刷新全部", width='stretch'):
            with st.spinner("蛋卷估值 + 黄金价格 + FRED宏观..."):
                res = fetch_all_valuations()
            st.success(f"数据更新完成：{list(res.keys())}")
            st.rerun()
    with col2:
        if st.button("🧪 蛋卷估值", width='stretch'):
            with st.spinner("获取纳指 + 中证红利官方估值..."):
                r = fetch_danjuan_valuation(force=True)
            if r:
                st.success(f"蛋卷估值已更新：{list(r.keys())}")
                st.rerun()
            else:
                st.warning("蛋卷估值更新失败（Cookie 过期？）")
    with col3:
        if st.button("🌐 黄金/白银价格", width='stretch'):
            with st.spinner("获取 FMP 黄金价格..."):
                r = fetch_gold_price_from_fmp(force=True)
            if r:
                st.success(f"黄金价格已更新（Gold=${r.get('gold'):.1f}）")
                st.rerun()
            else:
                st.warning("黄金价格更新失败")
    with col4:
        if st.button("📊 FRED 宏观", width='stretch'):
            with st.spinner("获取 FRED 宏观数据..."):
                fetch_fred_metrics(history_days=30)
            st.success("FRED 宏观数据已更新（30天）")
            st.rerun()

    _render_api_key_config()

    st.divider()

    # 获取估值全景
    with st.spinner("计算估值评分..."):
        overview = get_valuation_overview()

    # ========== 第一行：三大资产统一评分卡 ==========
    st.subheader("🎯 三大资产估值评分（0便宜 / 100昂贵）")
    cols = st.columns(3)
    for i, a in enumerate(["nasdaq", "dividend", "gold"]):
        with cols[i]:
            _render_asset_card(a, overview["assets"][a])

    # ========== 第二行：资产排名 + 组合建议 ==========
    st.subheader("🏆 资产便宜度排名 + 组合配置建议")

    c_rank, c_suggest = st.columns([1, 1.3])
    with c_rank:
        st.markdown("**按便宜度从低到高：**")
        ranking = overview.get("ranking", [])
        if ranking:
            rank_rows = []
            for rank_i, (a_key, s) in enumerate(ranking, 1):
                asset_result = overview["assets"][a_key]
                rank_rows.append({
                    "排名": f"#{rank_i}",
                    "资产": ASSET_NAMES.get(a_key, a_key),
                    "估值分数": f"{s:.1f}",
                    "区间": asset_result.get("band", "—"),
                    "定投倍数": f"{asset_result.get('invest_multiplier', 0):.1f}x",
                })
            st.dataframe(pd.DataFrame(rank_rows), width='stretch', hide_index=True)
        else:
            st.info("暂无有效数据")

    with c_suggest:
        st.markdown("**💸 组合配置建议（¥1000 基础金额）**")
        suggestions = get_portfolio_suggestion(base_amount=1000.0)
        if suggestions:
            sug_rows = []
            for item in suggestions:
                sug_rows.append({
                    "资产": item["label"],
                    "估值分数": f"{item['score']:.1f}",
                    "区间": item["band"],
                    "建议金额": f"¥{item['amount']:.0f}",
                    "占比": f"{item['ratio']:.0f}%",
                    "倍数": f"{item['multiplier']:.1f}x",
                })
            st.dataframe(pd.DataFrame(sug_rows), width='stretch', hide_index=True)

            # 定投倍数输入
            base_amt = st.number_input("💰 自定义每次定投基础金额（¥）",
                                        min_value=100.0, max_value=100000.0,
                                        value=1000.0, step=100.0, key="base-amt")
            custom_sug = get_portfolio_suggestion(base_amount=base_amt)
            if custom_sug:
                st.markdown("**按该金额分配：**")
                for item in custom_sug:
                    color = _score_color(item["score"])
                    st.markdown(
                        f"- **{item['label']}**：¥{item['amount']:.0f} "
                        f"({item['ratio']:.0f}%) · "
                        f"<span style='color:{color}'>{item['band']}({item['score']:.0f}分)</span> · "
                        f"x{item['multiplier']}",
                        unsafe_allow_html=True
                    )
        else:
            st.info("暂无估值数据")

    # ========== 第三行：智能定投倍数总览 ==========
    st.divider()
    st.subheader("💸 各资产定投倍数一览")
    m_rows = []
    for a in ["nasdaq", "dividend", "gold"]:
        s = overview["assets"][a]
        mult = s.get("invest_multiplier", 0)
        score = s["score"]
        m_rows.append({
            "资产": ASSET_NAMES[a],
            "估值分数": f"{score:.0f}" if score is not None else "—",
            "区间": s.get("band", "—"),
            "定投倍数": f"{mult:.1f}x",
            "建议": s.get("recommendation", "—"),
        })
    st.dataframe(pd.DataFrame(m_rows), width='stretch', hide_index=True)

    # ========== 第四行：详细指标历史图 ==========
    st.divider()
    st.subheader("📈 关键指标历史走势")
    st.caption("实线=历史值，虚线=20%/50%/80%分位线，红钻=当前值")

    tab1, tab2, tab3 = st.tabs(["🔹 纳指指标", "🟧 红利指标", "🟨 黄金指标"])

    with tab1:
        st.markdown("**纳指100 估值（蛋卷官方，10年历史）**")
        c1, c2 = st.columns(2)
        with c1:
            _render_metric_chart("nasdaq", "qqq_pe", "纳指100 PE")
            _render_metric_chart("nasdaq", "qqq_peg", "纳指100 PEG")
        with c2:
            _render_metric_chart("nasdaq", "qqq_pb", "纳指100 PB（仅留存）")

    with tab2:
        st.markdown("**中证红利 估值（蛋卷官方，10年历史）**")
        c1, c2 = st.columns(2)
        with c1:
            _render_metric_chart("dividend", "csi_div_pe", "中证红利 PE")
            _render_metric_chart("dividend", "csi_div_pb", "中证红利 PB")
        with c2:
            _render_metric_chart("dividend", "csi_div_yield", "中证红利 股息率(%)")

    with tab3:
        st.markdown("**黄金 V5 估值体系（历史百分位法）**")
        c1, c2 = st.columns(2)
        with c1:
            _render_metric_chart("macro", "real_rate_10y", "10年TIPS实际利率(%)")
            _render_metric_chart("gold", "gold_crb_ratio", "黄金实际价格(Gold/PPI×100)")
        with c2:
            _render_metric_chart("gold", "gold_silver_ratio", "金银比")
            _render_metric_chart("macro", "commodity_index", "生产者价格指数(商品)")

    # ========== 第五行：宏观指标总览 ==========
    st.divider()
    st.subheader("🌐 宏观环境指标（影响评分的宏观修正因子）")
    macro_rows = []
    for m_key, m_meta in MACRO_META.items():
        latest = get_valuation_history(m_meta["asset"], m_key)
        cur = None
        data_date = "—"
        if latest and len(latest) > 0:
            try:
                cur = float(latest[-1]["value"])
                data_date = latest[-1].get("trade_date") or "—"
            except Exception:
                pass
        macro_rows.append({
            "指标": m_meta["label"],
            "最新值": _format_val(cur),
            "数据日期": data_date,
            "低位": f"{m_meta.get('low', '—')}",
            "中性": f"{m_meta.get('mid', '—')}",
            "高位": f"{m_meta.get('high', '—')}",
        })
    st.dataframe(pd.DataFrame(macro_rows), width='stretch', hide_index=True)

    # 数据可信赖度说明
    with st.expander("📌 数据可信赖度说明（重要）", expanded=False):
        st.markdown("""
- **✅ `full`**：指标有 60+ 天历史数据，使用 **百分位评分**（相对位置，最可靠）
- **⚠️ `limited`**：指标有 30-59 天历史，使用百分位评分（参考用）
- **🧪 `fallback`**：指标不足 30 天历史，使用 **常识区间评分**（临时估算）
- **❌ `no_data`**：无当前数据

> 📝 每天拉一次数据，积累 2-3 个月后百分位评分会非常可靠。初期先用常识区间做参考。
""")

    # 生成时间
    st.markdown(
        f"<div style='text-align:right;color:#888;font-size:0.85em'>"
        f"生成时间：{overview['generated_at']} | 窗口：{overview['window_years']} | "
        f"宏观修正：{'启用' if overview.get('macro_enabled') else '关闭'}"
        f"</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    render_valuation_panel()
