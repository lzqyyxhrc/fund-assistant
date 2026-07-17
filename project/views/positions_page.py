import streamlit as st
from components.charts import render_fund_net_value_chart, calculate_fund_metrics
from services.storage import get_category_names, save_config
from services.net_value_storage import load_net_value_history
from services.fund_fetcher import check_data_freshness, get_fund_name_by_code


def format_money(amount, pattern="¥{:,.2f}"):
    if st.session_state.get("privacy_mode", False):
        return "****"
    return pattern.format(amount)


def render_positions():
    config = st.session_state.config
    net_values = st.session_state.net_values

    freshness = check_data_freshness(net_values)
    if not freshness["all_fresh"]:
        st.warning("部分数据来自历史缓存，仅供参考")

    st.header("📈 持仓明细")
    category_names = get_category_names()

    net_value_history = load_net_value_history()

    if "edit_mode" not in st.session_state:
        st.session_state.edit_mode = False

    col_edit, col_save = st.columns([1, 1])
    with col_edit:
        if st.button("编辑模式" if not st.session_state.edit_mode else "退出编辑", type="primary" if st.session_state.edit_mode else "secondary", key="portfolio_edit_mode_btn"):
            st.session_state.edit_mode = not st.session_state.edit_mode
            if st.session_state.edit_mode:
                import copy
                st.session_state.edit_config = copy.deepcopy(st.session_state.config)
            else:
                if "edit_config" in st.session_state:
                    del st.session_state.edit_config
            st.rerun()

    with col_save:
        if st.session_state.edit_mode and st.button("💾 保存修改", key="save_all_portfolio", type="primary"):
            # 统一使用 akshare 查询的基金简称覆盖所有名称
            for cat in ["nasdaq", "dividend", "gold"]:
                for f in st.session_state.edit_config["funds"].get(cat, []):
                    code = f.get("code", "").strip()
                    if code:
                        akshare_name = get_fund_name_by_code(code)
                        if akshare_name:
                            f["name"] = akshare_name
            import copy
            st.session_state.config = copy.deepcopy(st.session_state.edit_config)
            save_config(st.session_state.config)
            st.success("保存成功！")
            st.rerun()

    if st.session_state.edit_mode and "edit_config" not in st.session_state:
        import copy
        st.session_state.edit_config = copy.deepcopy(st.session_state.config)

    work_config = st.session_state.get("edit_config", st.session_state.config) if st.session_state.edit_mode else st.session_state.config

    for category in ["nasdaq", "dividend", "gold"]:
        with st.expander(f"{category_names[category]}", expanded=True):
            funds = work_config["funds"].get(category, [])

            if st.session_state.edit_mode:
                for i, fund in enumerate(funds):
                    with st.container():
                        col_code, col_shares, col_cost, col_del = st.columns([2, 2, 2, 1])

                        with col_code:
                            fund["code"] = st.text_input("代码", fund.get("code", ""), key=f"edit_code_{category}_{i}", label_visibility="collapsed")

                        with col_shares:
                            fund["shares"] = st.number_input("份额", value=float(fund.get("shares", 0.0)), step=0.01, key=f"edit_shares_{category}_{i}", label_visibility="collapsed")

                        with col_cost:
                            fund["cost_price"] = st.number_input("成本", value=float(fund.get("cost_price", 0.0)), step=0.0001, format="%.4f", key=f"edit_cost_{category}_{i}", label_visibility="collapsed")

                        with col_del:
                            if st.button("删除", key=f"del_{category}_{i}", type="secondary"):
                                st.session_state.edit_config["funds"][category].pop(i)
                                st.rerun()

                        st.divider()

                if st.button(f"+ 添加{category_names[category]}基金", key=f"edit_add_{category}"):
                    if category not in st.session_state.edit_config["funds"]:
                        st.session_state.edit_config["funds"][category] = []
                    st.session_state.edit_config["funds"][category].append({
                        "name": "",
                        "code": "",
                        "shares": 0.0,
                        "cost_price": 0.0
                    })
                    st.rerun()

            else:
                if funds:
                    data = []
                    for fund in funds:
                        if fund["code"] in net_values:
                            nv = net_values[fund["code"]]
                            cost_price = fund.get("cost_price", 0.0)
                            shares = fund.get("shares", 0.0)
                            pending_orders = fund.get("pending_orders", [])
                            pending_amount = sum(order.get("amount", 0) for order in pending_orders)

                            market_value = shares * nv["net_value"]
                            cost_value = shares * cost_price if cost_price > 0 else 0
                            profit = market_value - cost_value
                            profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0

                            net_value_str = f"¥{nv['net_value']:.4f}"
                            if "date" in nv:
                                from datetime import datetime
                                today = datetime.now().strftime("%Y-%m-%d")
                                if nv["date"] != today:
                                    net_value_str += f" ({nv['date']})"

                            metrics = calculate_fund_metrics(fund["code"], net_value_history, "成立以来")
                            annualized_return = f"{metrics['annualized_return'] * 100:.2f}%" if metrics['annualized_return'] is not None else "-"
                            max_drawdown = f"{metrics['max_drawdown'] * 100:.2f}%" if metrics['max_drawdown'] is not None else "-"
                            sharpe_ratio = f"{metrics['sharpe_ratio']:.2f}" if metrics['sharpe_ratio'] is not None else "-"

                            if st.session_state.get("privacy_mode", False):
                                data.append({
                                    "基金名称": fund["name"],
                                    "代码": fund["code"],
                                    "待确认金额": "****" if pending_amount > 0 else "-",
                                    "成本价": "****",
                                    "最新净值": net_value_str,
                                    "持仓市值": "****",
                                    "持仓成本": "****",
                                    "盈亏金额": "****",
                                    "盈亏比例": f"{profit_pct:.2f}%",
                                    "年化收益": annualized_return,
                                    "最大回撤": max_drawdown,
                                    "夏普比率": sharpe_ratio
                                })
                            else:
                                data.append({
                                    "基金名称": fund["name"],
                                    "代码": fund["code"],
                                    "待确认金额": f"¥{pending_amount:.2f}" if pending_amount > 0 else "-",
                                    "成本价": f"¥{cost_price:.4f}",
                                    "最新净值": net_value_str,
                                    "持仓市值": f"¥{market_value:,.2f}",
                                    "持仓成本": f"¥{cost_value:,.2f}",
                                    "盈亏金额": f"¥{profit:,.2f}",
                                    "盈亏比例": f"{profit_pct:.2f}%",
                                    "年化收益": annualized_return,
                                    "最大回撤": max_drawdown,
                                    "夏普比率": sharpe_ratio
                                })
                    st.dataframe(data, width='stretch', hide_index=True)

                    has_pending = any(sum(order.get("amount", 0) for order in f.get("pending_orders", [])) > 0 for f in funds)
                    if has_pending:
                        st.info("部分金额处于待确认状态，待净值日期的净值更新后自动确认（份额=待确认金额/净值日期净值），不参与当前市值计算")
                else:
                    st.write("暂无持仓")

    st.divider()
    
    st.subheader("📈 基金净值走势")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 更新历史数据", width='stretch'):
            from services.fund_fetcher import batch_update_history_net_value
            
            all_codes = []
            for category in ["nasdaq", "dividend", "gold"]:
                funds = config["funds"].get(category, [])
                for fund in funds:
                    if fund["code"]:
                        all_codes.append(fund["code"])
            
            with st.spinner("正在获取历史净值..."):
                batch_update_history_net_value(all_codes)
            
            st.success("历史净值更新完成！")
            st.rerun()
    
    net_value_history = load_net_value_history()
    
    if not net_value_history:
        st.info("暂无净值历史数据")
    else:
        category_names = get_category_names()
        
        all_funds = []
        for category in ["nasdaq", "dividend", "gold"]:
            funds = config["funds"].get(category, [])
            for fund in funds:
                if fund["code"] in net_values:
                    all_funds.append({
                        "code": fund["code"],
                        "name": fund["name"],
                        "category": category
                    })
        
        if not all_funds:
            st.info("当前持仓基金暂无净值历史数据")
        else:
            col1, col2 = st.columns(2)
            with col1:
                selected_fund = st.selectbox(
                    "选择基金",
                    options=range(len(all_funds)),
                    format_func=lambda i: f"{all_funds[i]['name']} ({all_funds[i]['code']})"
                )
            with col2:
                time_range = st.radio(
                    "时间范围",
                    options=["今年以来", "成立以来"],
                    index=0,
                    horizontal=True
                )
            
            if selected_fund is not None:
                fund = all_funds[selected_fund]
                chart = render_fund_net_value_chart(fund["code"], fund["name"], net_value_history, time_range)
                
                if chart:
                    st.plotly_chart(chart, width='stretch')
                else:
                    st.info(f"基金 {fund['code']} 在所选时间范围内暂无净值数据")