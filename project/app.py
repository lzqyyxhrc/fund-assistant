import os
# 自动加载项目根目录 .env（若存在），把 FRED/FMP/DANJUAN_COOKIE/DEEPSEEK_API_KEY 等注入环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

import streamlit as st
from datetime import datetime
from services.storage import load_config, save_config
from services.fund_fetcher import get_fund_batch_net_value, check_data_freshness, get_fund_name_by_code
from services.calculator import calculate_category_value, calculate_current_weights
from services.auto_invest import confirm_pending_shares, sync_today_pending_orders_from_history
from services.scheduler import start_scheduler, is_scheduler_running
from views.dashboard_page import render_dashboard
from views.positions_page import render_positions
from views.valuation_page import render_valuation
from views.auto_invest_page import render_auto_invest
from views.index_analysis_page import render_index_analysis
from components.data_center import render_data_center

st.set_page_config(
    page_title="基金智能定投再平衡",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown(
    """
    <style>
    /* 隐藏 Streamlit 默认元素 */
    [data-testid="stStatusWidget"],
    .stDeployButton,
    #MainMenu {
        display: none !important;
    }

    /* ========== 通用移动端适配 ========== */
    @media (max-width: 768px) {
        /* 缩小整体字体 */
        html, body, .stApp {
            font-size: 14px;
        }
        h1 {
            font-size: 1.4rem !important;
        }
        h2 {
            font-size: 1.15rem !important;
        }
        h3 {
            font-size: 1rem !important;
        }

        /* 让 columns 在小屏上竖排 */
        .stColumn, [data-testid="column"] {
            min-width: 100% !important;
            width: 100% !important;
            flex: 0 0 100% !important;
        }
        .row-widget.stHorizontal {
            flex-direction: column !important;
            flex-wrap: wrap !important;
        }

        /* 修正 st.columns(N) 内部排列 */
        section > div:has(> .stHorizontal) {
            flex-wrap: wrap !important;
        }
        .stHorizontal > div {
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        /* 按钮全宽 + 大间距方便触屏 */
        .stButton button, .stDownloadButton button {
            width: 100% !important;
            min-height: 44px;
            font-size: 15px !important;
        }

        /* 输入框 / 选择框 触屏友好 */
        input, select, textarea, .stSelectbox, .stTextInput {
            font-size: 16px !important;
            min-height: 44px;
        }

        /* Metric 卡片紧凑 */
        [data-testid="metric-container"] {
            padding: 8px !important;
        }
        [data-testid="metric-container"] label {
            font-size: 12px !important;
        }
        [data-testid="metric-container"] [data-testid="stMetricValue"] {
            font-size: 18px !important;
        }

        /* 带边框容器（各类资产总收益卡片） */
        [data-testid="stVerticalBlockBorderainer"] {
            padding: 10px !important;
        }

        /* 表格水平滚动 */
        .stDataFrame, [data-testid="stDataFrame"] {
            overflow-x: auto !important;
            max-width: 100% !important;
        }
        .stDataFrame table {
            font-size: 12px !important;
        }

        /* Plotly 图表自适应宽度 */
        .stPlotlyChart, .js-plotly-plot, .plot-container {
            width: 100% !important;
            max-width: 100% !important;
        }

        /* 侧边栏（导航菜单）在手机上全屏覆盖 */
        [data-testid="stSidebar"] {
            width: 100% !important;
            max-width: 100% !important;
        }
        [data-testid="stSidebar"] .stRadio label {
            font-size: 16px !important;
            padding: 8px 0 !important;
        }

        /* 警告/信息弹窗 */
        .stAlert {
            font-size: 13px !important;
        }

        /* 标题下方间距调整 */
        .stApp header {
            height: 0 !important;
        }
        .block-container {
            padding-top: 1rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }

        /* toggle 开关适配 */
        .stToggle {
            min-height: 44px;
        }

        /* caption 缩小 */
        .stCaption {
            font-size: 11px !important;
        }
    }

    /* 平板（768-1024px）适度适配 */
    @media (min-width: 769px) and (max-width: 1024px) {
        .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        .stHorizontal > div {
            min-width: 48%;
        }
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
    
    # 统一使用 akshare 查询的基金简称覆盖所有名称，并同步写入数据库
    need_save = False
    for cat in ["nasdaq", "dividend", "gold"]:
        for f in st.session_state.config["funds"].get(cat, []):
            code = f.get("code", "").strip()
            if code:
                akshare_name = get_fund_name_by_code(code)
                if akshare_name and f.get("name") != akshare_name:
                    f["name"] = akshare_name
                    need_save = True
    
    if need_save:
        save_config(st.session_state.config)
    
    # 必须先初始化 data_freshness，这样后续净值获取成功后才能正确记录时间戳
    if "data_freshness" not in st.session_state:
        st.session_state.data_freshness = {
            "nav": None,
            "valuation": None,
            "index": None,
        }
    
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
                st.session_state.data_freshness["nav"] = datetime.now()
            
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
    
    # 数据控制中心
    render_data_center()
    
    # 定时任务管理
    from components.scheduler_panel import render_scheduler_panel
    render_scheduler_panel()

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