import streamlit as st
from services.storage import load_config, save_config, load_threshold
from services.fund_fetcher import get_fund_batch_net_value, check_data_freshness
from services.calculator import calculate_category_value, calculate_current_weights, calculate_rebalancing_amounts, distribute_amount_to_funds, calculate_total_value
from services.auto_invest import load_auto_invest_config, save_auto_invest_config, execute_auto_invest, check_and_execute_auto_invest, should_auto_invest_now, confirm_pending_shares
from components.sidebar import render_sidebar
from components.dashboard import render_dashboard
from components.recommendation import render_recommendation
from components.auto_invest_panel import render_auto_invest_panel
from components.scheduler_panel import render_scheduler_panel

st.set_page_config(
    page_title="基金智能定投再平衡",
    page_icon="",
    layout="wide"
)

st.title("💰 基金投资管家")
st.markdown("智能定投 · 动态再平衡 · 实时监控您的基金组合")

if "config" not in st.session_state:
    st.session_state.config = load_config()

if "net_values" not in st.session_state:
    st.session_state.net_values = {}

if "rebalance_threshold" not in st.session_state:
    st.session_state.rebalance_threshold = load_threshold()

def confirm_pending_on_startup():
    """启动时确认待确认份额（需要先加载净值数据）"""
    if st.session_state.net_values:
        confirmed_count = confirm_pending_shares(st.session_state.config, st.session_state.net_values)
        if confirmed_count > 0:
            save_config(st.session_state.config)

def load_net_values_on_startup():
    all_codes = []
    for category in ["nasdaq", "dividend", "gold"]:
        for fund in st.session_state.config["funds"].get(category, []):
            if fund["code"]:
                all_codes.append(fund["code"])
    
    if all_codes and not st.session_state.net_values:
        with st.spinner("正在获取基金净值..."):
            try:
                st.session_state.net_values = get_fund_batch_net_value(all_codes)
                if not st.session_state.net_values:
                    st.warning("获取净值数据失败，正在尝试从历史缓存读取...")
                    st.session_state.net_values = get_fund_batch_net_value(all_codes, use_cache=True)
                
                if st.session_state.net_values:
                    freshness = check_data_freshness(st.session_state.net_values)
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
                    
                    if not freshness["all_fresh"]:
                        st.warning(f"警告: 部分基金使用历史数据（{' | '.join(source_info)}），原因可能是节假日或接口异常")
                else:
                    st.warning("无法获取净值数据，历史缓存也为空")
            except Exception as e:
                st.warning(f"获取净值数据失败: {str(e)}")
                st.session_state.net_values = get_fund_batch_net_value(all_codes, use_cache=True)
                if not st.session_state.net_values:
                    st.warning("历史缓存也为空")

load_net_values_on_startup()
confirm_pending_on_startup()

with st.sidebar:
    new_investment = render_sidebar()
    
    if st.button("保存配置"):
        save_config(st.session_state.config)
        st.success("配置已保存")
    
    if st.button("刷新数据"):
        with st.spinner("正在获取基金净值..."):
            all_codes = []
            for category in ["nasdaq", "dividend", "gold"]:
                for fund in st.session_state.config["funds"].get(category, []):
                    if fund["code"]:
                        all_codes.append(fund["code"])
            
            if all_codes:
                st.session_state.net_values = get_fund_batch_net_value(all_codes)
                
                # 检查并确认到期的待确认份额（使用最新净值）
                confirmed_count = confirm_pending_shares(st.session_state.config, st.session_state.net_values)
                if confirmed_count > 0:
                    save_config(st.session_state.config)
                
                freshness = check_data_freshness(st.session_state.net_values)
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
                
                if freshness["all_fresh"]:
                    st.success(f"数据已刷新（{' | '.join(source_info)}）")
                else:
                    st.warning(f"警告: 部分基金使用历史数据（{' | '.join(source_info)}），原因可能是节假日或接口异常")
            else:
                st.warning("请先配置基金代码")
    
    calculator_module = type('obj', (object,), {
        'calculate_category_value': calculate_category_value,
        'calculate_total_value': calculate_total_value,
        'calculate_rebalancing_amounts': calculate_rebalancing_amounts,
        'distribute_amount_to_funds': distribute_amount_to_funds
    })
    
    render_auto_invest_panel(
        st.session_state.config,
        st.session_state.net_values,
        calculator_module()
    )
    
    st.sidebar.divider()
    
    render_scheduler_panel()

main_container = st.container()

if st.session_state.net_values:
    category_values = calculate_category_value(st.session_state.config["funds"], st.session_state.net_values)
    total_value = sum(category_values.values())
    current_weights = calculate_current_weights(category_values, total_value)
    
    with main_container:
        render_dashboard(category_values, current_weights, st.session_state.config["targets"], st.session_state.net_values)
        render_recommendation(st.session_state.config["targets"], category_values, total_value, new_investment, st.session_state.config["funds"], st.session_state.net_values)
else:
    with main_container:
        st.info("请先在左侧配置基金代码")