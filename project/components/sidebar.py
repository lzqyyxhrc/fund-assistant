import streamlit as st
from services.storage import get_category_names, load_investment_amount, save_investment_amount, load_threshold, save_threshold

def add_fund_callback(category):
    if category not in st.session_state.config["funds"]:
        st.session_state.config["funds"][category] = []
    st.session_state.config["funds"][category].append({"code": "", "name": "新基金", "shares": 0.0, "cost_price": 0.0})

def del_fund_callback(category):
    if category in st.session_state.config["funds"] and st.session_state.config["funds"][category]:
        st.session_state.config["funds"][category].pop()

def render_sidebar():
    st.sidebar.title("资产配置")

    if "investment_amount" not in st.session_state:
        st.session_state.investment_amount = load_investment_amount()

    col1, col2 = st.sidebar.columns([3, 1])
    with col1:
        new_investment = st.number_input(
            "今日定投金额（元）",
            min_value=0,
            value=st.session_state.investment_amount,
            step=100,
            key="investment_input",
            help="输入今日计划定投的总金额"
        )
        st.session_state.investment_amount = new_investment
    with col2:
        st.write("")
        if st.button("💾 保存", key="save_investment", use_container_width=True):
            from services.storage import save_config
            save_config(st.session_state.config)
            save_investment_amount(new_investment)
            st.success("已保存！")
            st.rerun()

    if "rebalance_threshold" not in st.session_state:
        st.session_state.rebalance_threshold = load_threshold()

    col3, col4 = st.sidebar.columns([3, 1])
    with col3:
        threshold = st.slider(
            "偏离度阈值（%）",
            min_value=0.0,
            max_value=10.0,
            value=st.session_state.rebalance_threshold * 100,
            step=0.5,
            key="threshold_input",
            help="偏离度超过此阈值时触发再平衡定投策略"
        )
        st.session_state.rebalance_threshold = threshold / 100
    with col4:
        st.write("")
        if st.button("💾 保存", key="save_threshold", use_container_width=True):
            from services.storage import save_config
            save_config(st.session_state.config)
            save_threshold(threshold / 100)
            st.success("已保存！")
            st.rerun()

    st.sidebar.divider()
    
    category_names = get_category_names()
    
    for category in ["nasdaq", "dividend", "gold"]:
        with st.sidebar.expander(f"📊 {category_names[category]}"):
            funds = st.session_state.config["funds"].get(category, [])
            target_pct = st.session_state.config["targets"].get(category, 0) * 100
            
            st.write(f"目标仓位: {target_pct:.1f}%")
            
            for i, fund in enumerate(funds):
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    updated_name = st.text_input(f"基金名称 {i+1}", fund["name"], key=f"{category}_name_{i}")
                    fund["name"] = updated_name
                with col2:
                    updated_code = st.text_input(f"代码 {i+1}", fund["code"], key=f"{category}_code_{i}")
                    fund["code"] = updated_code
                with col3:
                    updated_shares = st.number_input(
                        f"份额 {i+1}",
                        value=float(fund["shares"]),
                        key=f"{category}_shares_{i}",
                        step=0.01,
                        format="%.2f"
                    )
                    fund["shares"] = updated_shares
                with col4:
                    cost_price = fund.get("cost_price", 0.0)
                    updated_cost = st.number_input(
                        f"成本 {i+1}",
                        value=float(cost_price),
                        key=f"{category}_cost_{i}",
                        step=0.0001,
                        format="%.4f"
                    )
                    fund["cost_price"] = updated_cost
            
            st.button(
                f"添加基金",
                key=f"add_{category}",
                on_click=add_fund_callback,
                args=(category,)
            )
            
            if funds:
                st.button(
                    f"删除最后一个",
                    key=f"del_{category}",
                    on_click=del_fund_callback,
                    args=(category,)
                )
    
    return new_investment