import os
# 自动加载项目根目录 .env（若存在），把 FRED/FMP/DANJUAN_COOKIE/DEEPSEEK_API_KEY 等注入环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

import streamlit as st
from services.storage import load_config, save_config
from services.fund_fetcher import get_fund_batch_net_value, check_data_freshness
from services.calculator import calculate_category_value, calculate_current_weights
from services.auto_invest import confirm_pending_shares, sync_today_pending_orders_from_history
from services.scheduler import start_scheduler, is_scheduler_running
from views.dashboard_page import render_dashboard
from views.positions_page import render_positions
from views.valuation_page import render_valuation
from views.auto_invest_page import render_auto_invest
from views.index_analysis_page import render_index_analysis

st.set_page_config(
    page_title="基金智能定投再平衡",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    [data-testid="stStatusWidget"] {
        display: none !important;
    }
    .stDeployButton {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

if not is_scheduler_running():
    start_scheduler()

def refresh_data():
    st.session_state.config = load_config()
    st.session_state.targets = st.session_state.config.get("targets", {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2})
    
    st.session_state.net_values = {}
    all_codes = []
    for category in ["nasdaq", "dividend", "gold"]:
        for fund in st.session_state.config["funds"].get(category, []):
            if fund["code"]:
                all_codes.append(fund["code"])
    
    if all_codes:
        try:
            st.session_state.net_values = get_fund_batch_net_value(all_codes)
            if not st.session_state.net_values:
                st.session_state.net_values = get_fund_batch_net_value(all_codes, use_cache=True)
            
            if st.session_state.net_values:
                freshness = check_data_freshness(st.session_state.net_values)
                if not freshness["all_fresh"]:
                    sources = freshness.get("sources", {})
                    source_info = []
                    if sources.get("akshare", 0) > 0:
                        source_info.append(f"AkShare:{sources['akshare']}")
                    if sources.get("eastmoney", 0) > 0:
                        source_info.append(f"天天基金:{sources['eastmoney']}")
                    if sources.get("cache", 0) > 0:
                        source_info.append(f"缓存:{sources['cache']}")
                    if sources.get("cache_fallback", 0) > 0:
                        source_info.append(f"缓存兜底:{sources['cache_fallback']}")
                    st.warning(f"警告: 部分基金使用历史数据（{' | '.join(source_info)}），原因可能是节假日或接口异常")
        except Exception as e:
            st.session_state.net_values = get_fund_batch_net_value(all_codes, use_cache=True)
    
    if "rebalance_threshold" not in st.session_state:
        st.session_state.rebalance_threshold = 5.0
    
    if "privacy_mode" not in st.session_state:
        st.session_state.privacy_mode = False

def init_global_state():
    if "config" not in st.session_state:
        refresh_data()
    
    if "targets" not in st.session_state:
        st.session_state.targets = st.session_state.config.get("targets", {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2})
    
    if "net_values" not in st.session_state or not st.session_state.net_values:
        refresh_data()
    
    if "rebalance_threshold" not in st.session_state:
        st.session_state.rebalance_threshold = 5.0
    
    if "privacy_mode" not in st.session_state:
        st.session_state.privacy_mode = False

init_global_state()

if sync_today_pending_orders_from_history(st.session_state.config) > 0:
    save_config(st.session_state.config)

if st.session_state.net_values:
    confirmed_count = confirm_pending_shares(st.session_state.config, st.session_state.net_values)
    if confirmed_count > 0:
        save_config(st.session_state.config)

with st.sidebar:
    st.title("💰 基金投资管家")
    st.markdown("智能定投 · 动态再平衡 · 实时监控")
    st.divider()
    
    page = st.radio(
        "导航菜单",
        ["仪表盘", "持仓明细", "估值分析", "定投计划", "指数分析"],
        key="page_nav"
    )
    
    st.divider()
    if st.button("🔄 刷新数据", use_container_width=True):
        refresh_data()
        st.success("数据已刷新")

st.title("基金投资管家")

if page == "仪表盘":
    render_dashboard()
elif page == "持仓明细":
    render_positions()
elif page == "估值分析":
    render_valuation()
elif page == "定投计划":
    render_auto_invest()
elif page == "指数分析":
    render_index_analysis()