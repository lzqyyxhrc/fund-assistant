"""
数据控制中心 — 统一管理所有数据刷新操作

在侧边栏展示数据新鲜度状态，提供一键刷新和按类刷新功能。
各页面不再保留数据刷新按钮，仅保留编辑/操作类功能。
"""

import streamlit as st
from datetime import datetime


def _time_ago(timestamp):
    """返回人类可读的时间差"""
    if timestamp is None:
        return "从未"
    delta = datetime.now() - timestamp
    if delta.total_seconds() < 60:
        return "刚刚"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() / 60)} 分钟前"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() / 3600)} 小时前"
    return f"{int(delta.total_seconds() / 86400)} 天前"


def _freshness_tag(timestamp):
    """返回数据新鲜度标签"""
    if timestamp is None:
        return "⚪ 未刷新"
    delta = datetime.now() - timestamp
    if delta.total_seconds() < 3600:
        return "🟢 新鲜"
    if delta.total_seconds() < 21600:
        return "🟡 较旧"
    return "🔴 过期"


def _refresh_nav():
    """刷新净值数据（无 UI 副作用，仅更新 st.session_state）"""
    from services.storage import load_config
    from services.fund_fetcher import get_fund_batch_net_value

    config = load_config()
    all_codes = []
    for cat in ["nasdaq", "dividend", "gold"]:
        for fund in config["funds"].get(cat, []):
            if fund["code"]:
                all_codes.append(fund["code"])

    if not all_codes:
        st.warning("未配置基金，无法刷新净值")
        return

    net_values = get_fund_batch_net_value(all_codes)
    if not net_values:
        net_values = get_fund_batch_net_value(all_codes, use_cache=True)

    if net_values:
        st.session_state.net_values = net_values
        st.session_state.data_freshness["nav"] = datetime.now()
        st.success(f"净值已更新（{len(net_values)} 只基金）")
    else:
        st.error("净值获取失败，请稍后重试")


def _refresh_valuation():
    """刷新估值数据"""
    from services.valuation_fetcher import fetch_all_valuations

    res = fetch_all_valuations()
    if res:
        st.session_state.data_freshness["valuation"] = datetime.now()
        st.success(f"估值已更新（{len(res)} 项指标）")
    else:
        st.warning("估值获取失败，请检查 API Key / Cookie 配置")


def _refresh_report():
    """生成日报并推送到飞书"""
    from daily_report import generate_daily_report, save_report, send_to_feishu
    from services.auto_invest import load_auto_invest_config

    auto_cfg = load_auto_invest_config()
    api_key = auto_cfg.get("report_api_key", "")
    feishu_webhook = auto_cfg.get("feishu_webhook", "")

    report = generate_daily_report(api_key=api_key)
    if report:
        save_report(report)
        msg = "日报已生成"
        if feishu_webhook:
            send_to_feishu(report, feishu_webhook)
            msg += "，并推送到飞书"
        st.success(msg)
    else:
        st.error("日报生成失败")


def render_data_center():
    """渲染侧边栏数据控制中心"""
    freshness = st.session_state.get("data_freshness", {})

    with st.expander("📊 数据控制中心", expanded=True):
        # ── 数据新鲜度 ──
        st.markdown("**数据新鲜度**")
        for key, label in [("nav", "净值"), ("valuation", "估值"), ("index", "指数")]:
            ts = freshness.get(key)
            tag = _freshness_tag(ts)
            ago = _time_ago(ts)
            st.caption(f"{label}: {tag}（{ago}）")

        st.divider()

        # ── 一键全刷新 ──
        if st.button("🔄 刷新全部数据", type="primary", use_container_width=True):
            with st.status("正在刷新全部数据...", expanded=True) as status:
                st.write("① 刷新基金净值...")
                _refresh_nav()
                st.write("② 刷新估值数据...")
                _refresh_valuation()
                st.write("③ 刷新完成")
                status.update(label="全部数据已刷新", state="complete", expanded=False)
            st.rerun()

        # ── 分别刷新 ──
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📈 净值", use_container_width=True):
                with st.spinner("获取基金净值..."):
                    _refresh_nav()
                st.rerun()
        with col2:
            if st.button("📊 估值", use_container_width=True):
                with st.spinner("获取估值数据..."):
                    _refresh_valuation()
                st.rerun()
        with col3:
            if st.button("📝 日报", use_container_width=True):
                with st.spinner("生成日报..."):
                    _refresh_report()
                st.rerun()
