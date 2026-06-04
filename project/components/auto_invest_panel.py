import streamlit as st
from datetime import datetime
from services.auto_invest import load_auto_invest_config, save_auto_invest_config, load_invest_history, save_invest_history, has_invested_today
from services.storage import save_config

def add_auto_fund_callback():
    if "auto_invest_funds" not in st.session_state:
        st.session_state.auto_invest_funds = []
    st.session_state.auto_invest_funds.append({"code": "", "amount": 0})

def del_auto_fund_callback():
    if "auto_invest_funds" in st.session_state and st.session_state.auto_invest_funds:
        st.session_state.auto_invest_funds.pop()

def render_auto_invest_panel(funds_config, net_values, calculator):
    st.sidebar.divider()
    st.sidebar.title("定投计划")
    
    auto_config = load_auto_invest_config()
    
    auto_config["enabled"] = st.sidebar.toggle(
        "启用自动定投",
        value=auto_config.get("enabled", False),
        help="开启后每天自动执行定投"
    )

    if auto_config["enabled"] != load_auto_invest_config().get("enabled"):
        save_auto_invest_config(auto_config)
        if auto_config["enabled"]:
            st.sidebar.success("自动定投已启用")
        else:
            st.sidebar.info("自动定投已关闭")

    if "auto_invest_funds" not in st.session_state:
        st.session_state.auto_invest_funds = auto_config.get("auto_invest_funds", [])
    
    st.sidebar.subheader("定投基金列表")
    
    for i, fund in enumerate(st.session_state.auto_invest_funds):
        col1, col2, col3 = st.sidebar.columns([2, 2, 1])
        with col1:
            updated_code = st.text_input(f"基金代码 {i+1}", fund["code"], key=f"auto_fund_code_{i}")
            fund["code"] = updated_code
        with col2:
            updated_amount = st.number_input(
                f"每日金额 {i+1}",
                min_value=0,
                value=fund["amount"],
                step=10,
                key=f"auto_fund_amount_{i}"
            )
            fund["amount"] = updated_amount
        with col3:
            st.write(f"¥{fund['amount']}")
    
    st.sidebar.button(
        "添加基金",
        key="add_auto_fund",
        on_click=add_auto_fund_callback
    )
    
    if st.session_state.auto_invest_funds:
        st.sidebar.button(
            "删除最后一个",
            key="del_auto_fund",
            on_click=del_auto_fund_callback
        )
    
    total_daily = sum(f["amount"] for f in st.session_state.auto_invest_funds)
    st.sidebar.write(f"**每日定投总额**: ¥{total_daily}")
    
    if st.sidebar.button("保存定投计划"):
        auto_config["auto_invest_funds"] = st.session_state.auto_invest_funds
        save_auto_invest_config(auto_config)
        st.sidebar.success("定投计划已保存")
    
    st.sidebar.divider()
    st.sidebar.title("定投历史")
    
    history = load_invest_history()
    if history:
        recent_history = history[-5:]
        for record in reversed(recent_history):
            st.sidebar.write(f"**{record['date']}**: ¥{record['total_amount']:.2f}")
    else:
        st.sidebar.write("暂无定投记录")

def find_fund_category(funds_config, code):
    for category, funds in funds_config["funds"].items():
        for fund in funds:
            if fund["code"] == code:
                return category
    return None