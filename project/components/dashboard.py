import streamlit as st
from components.charts import render_pie_chart, render_bar_chart, render_fund_net_value_chart, calculate_fund_metrics
from components.index_chart import render_index_comparison_chart, get_index_performance, get_portfolio_performance
from services.storage import get_category_names, get_category_color, save_config
from services.fund_fetcher import check_data_freshness, get_fund_name_by_code
from services.net_value_storage import get_fund_history_data, load_net_value_history


def format_money(amount, pattern="¥{:,.2f}"):
    """格式化金额，隐私模式下返回 ****"""
    if st.session_state.get("privacy_mode", False):
        return "****"
    return pattern.format(amount)


def render_dashboard(category_values, current_weights, targets, net_values):
    total_value = sum(category_values.values())
    
    # 隐私开关（放在最前面）
    privacy_col, _ = st.columns([1, 4])
    with privacy_col:
        st.session_state["privacy_mode"] = st.toggle("🔒 隐私模式", value=st.session_state.get("privacy_mode", False))

    total_cost, total_profit, total_profit_pct = calculate_total_profit(st.session_state.config, net_values)
    yesterday_profit, yesterday_profit_pct = calculate_yesterday_profit(st.session_state.config, net_values)

    freshness = check_data_freshness(net_values)
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
        st.warning(f"警告: 部分数据来自历史缓存（{' | '.join(source_info)}），仅供参考")

    st.header("📈 资产概览")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总资产", format_money(total_value))
    with col2:
        st.metric("持仓成本", format_money(total_cost))
    with col3:
        st.metric("持仓收益", format_money(total_profit), delta=f"{total_profit_pct:.2f}%" if not st.session_state.get("privacy_mode", False) else "", delta_color="normal" if total_profit >= 0 else "inverse")
    with col4:
        st.metric("基金数量", sum(len(funds) for funds in st.session_state.config["funds"].values()))
    
    st.subheader("各类资产总收益")
    
    category_cost, category_market, category_profit, category_profit_pct = calculate_category_total_profit(st.session_state.config, net_values)
    category_names = get_category_names()
    
    col1, col2, col3 = st.columns(3)
    for i, category in enumerate(["nasdaq", "dividend", "gold"]):
        with [col1, col2, col3][i]:
            with st.container(border=True):
                st.write(f"**{category_names[category]}**")
                st.write(f"市值: {format_money(category_market[category])}")
                st.write(f"成本: {format_money(category_cost[category])}")
                profit_color = "green" if category_profit[category] >= 0 else "red"
                if st.session_state.get("privacy_mode", False):
                    st.write(f"收益: {format_money(category_profit[category])}")
                else:
                    st.write(f"收益: <span style='color:{profit_color};font-weight:bold'>{'+' if category_profit[category] >= 0 else ''}¥{category_profit[category]:,.2f} ({category_profit_pct[category]:.2f}%)</span>", unsafe_allow_html=True)
    
    st.subheader("昨日收益")
    
    # 检查是否有缓存数据
    freshness = check_data_freshness(net_values)
    has_cache_data = not freshness["all_fresh"]
    
    # 检查是否有任何有效数据可以计算昨日收益
    has_valid_data = False
    for category in ["nasdaq", "dividend", "gold"]:
        funds = st.session_state.config["funds"].get(category, [])
        for fund in funds:
            if fund["code"] in net_values:
                data_date = net_values[fund["code"]].get("date", "")
                from datetime import datetime, timedelta
                today = datetime.now().strftime("%Y-%m-%d")
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                day_before_yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
                
                if category == "nasdaq":
                    if data_date in [today, yesterday, day_before_yesterday]:
                        has_valid_data = True
                        break
                else:
                    if data_date in [today, yesterday]:
                        has_valid_data = True
                        break
        if has_valid_data:
            break
    
    if not has_valid_data:
        # 没有任何有效数据可以计算昨日收益
        st.info("当前净值数据过于陈旧，无法计算昨日收益")
    else:
        if has_cache_data:
            st.caption("部分基金使用缓存数据，昨日收益按可用历史净值估算")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("昨日收益金额", format_money(yesterday_profit), delta=f"{yesterday_profit_pct:.2f}%", delta_color="normal" if yesterday_profit >= 0 else "inverse")
        with col2:
            # 计算各类资产的昨日收益
            category_yesterday_profit = calculate_category_yesterday_profit(st.session_state.config, net_values)
            category_names = get_category_names()
            
            # 检查是否有有效数据
            if sum(category_yesterday_profit.values()) == 0.0:
                # 只有当所有类别收益都为0时才显示提示
                if has_cache_data:
                    st.info("部分基金使用缓存数据，收益计算可能不完整")
                else:
                    st.info("今日暂无收益变动")
            else:
                if st.session_state.get("privacy_mode", False):
                    profit_text = "<br>".join([f"{category_names[k]}: ****" for k, v in category_yesterday_profit.items()])
                else:
                    profit_text = "<br>".join([f"{category_names[k]}: {'+' if v >= 0 else ''}¥{v:,.2f}" for k, v in category_yesterday_profit.items()])
                st.markdown(f"**各类资产收益：**<br>{profit_text}", unsafe_allow_html=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(render_pie_chart(category_values, targets), width='stretch')
    with col2:
        st.plotly_chart(render_bar_chart(current_weights, targets), width='stretch')
    
    st.divider()

    st.subheader("持仓明细")
    category_names = get_category_names()

    # 加载净值历史数据用于计算指标
    net_value_history = load_net_value_history()

    # 编辑模式切换
    if "edit_mode" not in st.session_state:
        st.session_state.edit_mode = False

    col_edit, col_save = st.columns([1, 1])
    with col_edit:
        if st.button("编辑模式" if not st.session_state.edit_mode else "退出编辑", type="primary" if st.session_state.edit_mode else "secondary", key="portfolio_edit_mode_btn"):
            st.session_state.edit_mode = not st.session_state.edit_mode
            if st.session_state.edit_mode:
                # 进入编辑模式时，深拷贝配置到临时变量
                import copy
                st.session_state.edit_config = copy.deepcopy(st.session_state.config)
            else:
                # 退出编辑时清除临时变量
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

    # 确保编辑模式下 edit_config 始终可用
    if st.session_state.edit_mode and "edit_config" not in st.session_state:
        import copy
        st.session_state.edit_config = copy.deepcopy(st.session_state.config)

    # 编辑模式使用 edit_config，否则用 config
    work_config = st.session_state.get("edit_config", st.session_state.config) if st.session_state.edit_mode else st.session_state.config

    for category in ["nasdaq", "dividend", "gold"]:
        with st.expander(f"{category_names[category]}", expanded=True):
            funds = work_config["funds"].get(category, [])

            if st.session_state.edit_mode:
                # 编辑模式：显示可编辑的卡片（名称自动根据代码查询，无需手动输入）
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

                # 添加新基金按钮
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
                # 查看模式：显示只读数据
                if funds:
                    data = []
                    for fund in funds:
                        if fund["code"] in net_values:
                            nv = net_values[fund["code"]]
                            cost_price = fund.get("cost_price", 0.0)
                            shares = fund.get("shares", 0.0)
                            # 计算待确认金额（支持多笔待确认订单）
                            pending_orders = fund.get("pending_orders", [])
                            pending_amount = sum(order.get("amount", 0) for order in pending_orders)

                            # 只计算已确认份额的市值
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

                            # 计算基金指标（使用成立以来的数据）
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

                    # 显示待确认金额提示
                    has_pending = any(sum(order.get("amount", 0) for order in f.get("pending_orders", [])) > 0 for f in funds)
                    if has_pending:
                        st.info("部分金额处于待确认状态，待净值日期的净值更新后自动确认（份额=待确认金额/净值日期净值），不参与当前市值计算")
                else:
                    st.write("暂无持仓")
    
    st.divider()
    
    st.subheader("📈 基金净值走势")
    
    # 添加更新历史净值按钮
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 更新历史数据", width='stretch'):
            from services.fund_fetcher import batch_update_history_net_value
            
            all_codes = []
            for category in ["nasdaq", "dividend", "gold"]:
                funds = st.session_state.config["funds"].get(category, [])
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
            funds = st.session_state.config["funds"].get(category, [])
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

    st.divider()
    
    st.subheader("📊 指数对比分析")
    
    # 指数对比图
    index_chart = render_index_comparison_chart()
    if index_chart:
        st.plotly_chart(index_chart, width='stretch')
        
        # 显示指数表现数据
        performance = get_index_performance()
        if performance:
            st.markdown("### 指数表现对比")
            col1, col2, col3 = st.columns(3)
            for i, p in enumerate(performance):
                with [col1, col2, col3][i]:
                    with st.container(border=True):
                        st.write(f"**{p['name']}**")
                        profit_color = "green" if p['total_return'] >= 0 else "red"
                        st.write(f"累计收益: <span style='color:{profit_color};font-weight:bold'>{'+' if p['total_return'] >= 0 else ''}{p['total_return']}%</span>", unsafe_allow_html=True)
                        st.write(f"年化收益: {p['annual_return']}%")
                        st.write(f"年化波动率: {p['annual_volatility']}%")
                        st.write(f"夏普比率: {p['sharpe_ratio']}")
                        drawdown_color = "red" if p['max_drawdown'] < 0 else "green"
                        st.write(f"最大回撤: <span style='color:{drawdown_color}'>{p['max_drawdown']}%</span>", unsafe_allow_html=True)
        
        st.markdown("*中证红利净收益指数数据来源：[中证指数官网](https://www.csindex.com.cn/#/indices/family/detail?indexCode=000922)*")
        
        # 显示投资组合策略表现
        portfolio_perf = get_portfolio_performance()
        if portfolio_perf:
            st.markdown("### 定投策略对比")
            col1, col2 = st.columns(2)
            for i, p in enumerate(portfolio_perf):
                with [col1, col2][i]:
                    with st.container(border=True):
                        st.write(f"**{p['name']}**")
                        st.write(f"累计投入: ¥{p['total_invested']:,.0f}")
                        st.write(f"期末总值: ¥{p['final_value']:,.2f}")
                        profit_color = "green" if p['profit'] >= 0 else "red"
                        st.write(f"投资收益: <span style='color:{profit_color};font-weight:bold'>{'+' if p['profit'] >= 0 else ''}¥{p['profit']:,.2f} ({p['total_return']}%)</span>", unsafe_allow_html=True)
                        st.write(f"年化收益: {p['annual_return']}%")
                        st.write(f"年化波动率: {p['annual_volatility']}%")
                        st.write(f"夏普比率: {p['sharpe_ratio']}")
                        drawdown_color = "red" if p['max_drawdown'] < 0 else "green"
                        st.write(f"最大回撤: <span style='color:{drawdown_color}'>{p['max_drawdown']}%</span>", unsafe_allow_html=True)
    else:
        st.info("暂无指数数据，请先下载指数数据")

    # ==================== 估值评分系统 ====================
    st.divider()
    from components.valuation_panel import render_valuation_panel
    render_valuation_panel()

    # ==================== 定投计划编辑模块 ====================
    st.divider()

    st.subheader("定投计划")

    # 加载定投配置和历史
    from services.auto_invest import load_auto_invest_config, save_auto_invest_config, load_invest_history

    auto_config = load_auto_invest_config()

    if "auto_invest_funds" not in st.session_state:
        st.session_state.auto_invest_funds = auto_config.get("auto_invest_funds", [])

    # 编辑模式切换
    if "auto_edit_mode" not in st.session_state:
        st.session_state.auto_edit_mode = False

    col_edit, _ = st.columns([1, 4])
    with col_edit:
        if st.button("编辑模式" if not st.session_state.auto_edit_mode else "退出编辑", type="primary" if st.session_state.auto_edit_mode else "secondary", key="auto_invest_edit_mode_btn"):
            st.session_state.auto_edit_mode = not st.session_state.auto_edit_mode
            st.rerun()

    # 定投基金列表
    st.markdown("**定投基金列表**")
    auto_funds = st.session_state.auto_invest_funds

    if st.session_state.auto_edit_mode:
        # 编辑模式
        for i, fund in enumerate(auto_funds):
            with st.container():
                col_code, col_cat, col_amount, col_del = st.columns([2, 1, 2, 1])

                with col_code:
                    fund["code"] = st.text_input("基金代码", fund.get("code", ""), key=f"auto_edit_code_{i}", label_visibility="collapsed")

                with col_cat:
                    fund["category"] = st.selectbox("类别", ["dividend", "nasdaq", "gold"], index=["dividend", "nasdaq", "gold"].index(fund.get("category", "dividend")), key=f"auto_edit_cat_{i}", label_visibility="collapsed")

                with col_amount:
                    fund["amount"] = st.number_input("每日金额", value=fund.get("amount", 0), min_value=0, step=10, key=f"auto_edit_amount_{i}", label_visibility="collapsed")

                with col_del:
                    if st.button("删除", key=f"auto_edit_del_{i}", type="secondary"):
                        st.session_state.auto_invest_funds.pop(i)
                        st.rerun()

                st.divider()

        # 添加按钮
        if st.button("+ 添加定投基金", key="auto_edit_add"):
            st.session_state.auto_invest_funds.append({"code": "", "category": "dividend", "amount": 0})
            st.rerun()

        # 保存按钮
        if st.button("保存定投计划", key="auto_edit_save", type="primary"):
            auto_config["auto_invest_funds"] = st.session_state.auto_invest_funds
            save_auto_invest_config(auto_config)
            st.success("定投计划已保存！")

    else:
        # 查看模式
        if auto_funds:
            data = []
            for fund in auto_funds:
                fund_name = ""
                for category in ["nasdaq", "dividend", "gold"]:
                    for f in st.session_state.config["funds"].get(category, []):
                        if f["code"] == fund["code"]:
                            fund_name = f["name"]
                            break

                if st.session_state.get("privacy_mode", False):
                    data.append({
                        "基金代码": fund["code"],
                        "基金名称": fund_name or "-",
                        "每日金额": "****"
                    })
                else:
                    data.append({
                        "基金代码": fund["code"],
                        "基金名称": fund_name or "-",
                        "每日金额": f"¥{fund.get('amount', 0):,.0f}"
                    })
            st.dataframe(data, width='stretch', hide_index=True)
        else:
            st.write("暂无定投计划")

    # 显示定投总额
    total_daily = sum(f.get("amount", 0) for f in auto_funds)
    if st.session_state.get("privacy_mode", False):
        st.markdown(f"**每日定投总额**: ****")
    else:
        st.markdown(f"**每日定投总额**: ¥{total_daily:,}")

    # 显示定投历史（表格形式，最多5条）
    st.markdown("**定投历史（近5日）**")
    history = load_invest_history()
    if history:
        # 获取当前所有待确认订单，用于判断状态
        pending_map = {}
        for category in st.session_state.config["funds"]:
            for fund in st.session_state.config["funds"][category]:
                code = fund.get("code", "")
                if not code:
                    continue
                for order in fund.get("pending_orders", []):
                    key = (order["pending_date"], code, order["amount"], order["net_value_date"])
                    pending_map[key] = True
        
        recent_history = history[-5:]  # 显示最近5条
        # 构建表格数据
        history_data = []
        for record in reversed(recent_history):
            transactions = record.get("transactions", [])
            for txn in transactions:
                # 从持仓配置中查找基金名称
                fund_name = txn.get("name", txn.get("code", "-"))
                if fund_name == txn.get("code", "-"):
                    # 如果name等于code，说明没有保存名称，需要从配置中查找
                    code = txn.get("code", "")
                    for category in ["nasdaq", "dividend", "gold"]:
                        for f in st.session_state.config["funds"].get(category, []):
                            if f.get("code") == code:
                                fund_name = f.get("name", code)
                                break
                        if fund_name != code:
                            break
                
                # 判断状态：是否还在待确认订单中
                txn_key = (
                    record["date"],
                    txn.get("code", "-"),
                    txn.get("amount", 0),
                    txn.get("net_value_date", "-")
                )
                is_pending = txn_key in pending_map
                status_icon = "⏳" if is_pending else "✅"
                
                if st.session_state.get("privacy_mode", False):
                    history_data.append({
                        "日期": record["date"],
                        "基金名称": fund_name,
                        "代码": txn.get("code", "-"),
                        "金额": "****",
                        "净值日期": txn.get("net_value_date", "-"),
                        "状态": status_icon
                    })
                else:
                    history_data.append({
                        "日期": record["date"],
                        "基金名称": fund_name,
                        "代码": txn.get("code", "-"),
                        "金额": f"¥{txn.get('amount', 0):.2f}",
                        "净值日期": txn.get("net_value_date", "-"),
                        "状态": status_icon
                    })
        if history_data:
            st.dataframe(history_data, width='stretch', hide_index=True)
        else:
            st.write("暂无定投记录")
    else:
        st.write("暂无定投记录")

def calculate_total_profit(config, net_values):
    total_cost = 0.0
    total_market = 0.0
    
    for category in ["nasdaq", "dividend", "gold"]:
        funds = config["funds"].get(category, [])
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                cost_price = fund.get("cost_price", 0.0)
                shares = fund["shares"]
                
                total_cost += shares * cost_price
                total_market += shares * nv["net_value"]
    
    total_profit = total_market - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
    
    return total_cost, total_profit, total_profit_pct

def calculate_yesterday_profit(config, net_values):
    """计算昨日收益（基于历史净值数据）
    
    使用历史净值数据直接计算：昨日收益 = 份额 × (当前净值 - 昨日净值)
    
    根据基金类型判断数据是否可用：
    - A股基金（红利/黄金）：T日净值在T日晚上公布，允许昨天的数据
    - QDII基金（纳指）：T日净值在T+1日晚上公布，允许前天的数据
    """
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    day_before_yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    
    yesterday_profit = 0.0
    yesterday_profit_pct = 0.0
    valid_data_value = 0.0  # 使用有效数据计算的市值
    
    for category in ["nasdaq", "dividend", "gold"]:
        funds = config["funds"].get(category, [])
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                shares = fund["shares"]
                net_value = nv["net_value"]
                
                data_date = nv.get("date", "")
                if not data_date:
                    continue
                
                # 获取历史净值数据，基准日取“当前净值日期的前一个交易日”
                fund_history = get_fund_history_data(fund["code"])
                previous_record = None
                for item in fund_history.values():
                    item_date = item.get("date", "")
                    if item_date < data_date and (previous_record is None or item_date > previous_record.get("date", "")):
                        previous_record = item
                
                if previous_record:
                    previous_net_value = previous_record["net_value"]
                    profit = shares * (net_value - previous_net_value)
                    yesterday_profit += profit
                    valid_data_value += shares * net_value
                elif "change" in nv and nv["change"] != 0:
                    # 如果没有历史数据，使用日涨幅估算（备选方案）
                    change_pct = nv["change"] / 100
                    if change_pct != -1:
                        yesterday_value = (shares * net_value) / (1 + change_pct)
                        yesterday_profit += (shares * net_value) - yesterday_value
                        valid_data_value += shares * net_value
    
    # 只有有效数据才计算收益率
    if valid_data_value > 0:
        denominator = valid_data_value - yesterday_profit
        if denominator > 0:
            yesterday_profit_pct = (yesterday_profit / denominator) * 100
    
    return yesterday_profit, yesterday_profit_pct

def calculate_category_total_profit(config, net_values):
    """计算各类资产的总收益（成本 vs 当前市值）"""
    category_cost = {"nasdaq": 0.0, "dividend": 0.0, "gold": 0.0}
    category_market = {"nasdaq": 0.0, "dividend": 0.0, "gold": 0.0}
    
    for category in ["nasdaq", "dividend", "gold"]:
        funds = config["funds"].get(category, [])
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                cost_price = fund.get("cost_price", 0.0)
                shares = fund["shares"]
                
                category_cost[category] += shares * cost_price
                category_market[category] += shares * nv["net_value"]
    
    # 计算总收益和收益率
    category_profit = {}
    category_profit_pct = {}
    for category in ["nasdaq", "dividend", "gold"]:
        category_profit[category] = category_market[category] - category_cost[category]
        category_profit_pct[category] = (category_profit[category] / category_cost[category] * 100) if category_cost[category] > 0 else 0
    
    return category_cost, category_market, category_profit, category_profit_pct

def calculate_category_yesterday_profit(config, net_values):
    """计算各类资产的昨日收益（基于最新净值日期与前一个交易日的净值差）"""
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    day_before_yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    
    category_profit = {"nasdaq": 0.0, "dividend": 0.0, "gold": 0.0}
    
    for category in ["nasdaq", "dividend", "gold"]:
        funds = config["funds"].get(category, [])
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                shares = fund["shares"]
                net_value = nv["net_value"]
                data_date = nv.get("date", "")
                if not data_date:
                    continue
                
                # 获取历史净值，找当前净值日期的前一个交易日
                fund_history = get_fund_history_data(fund["code"])
                previous_record = None
                for item in fund_history.values():
                    item_date = item.get("date", "")
                    if item_date < data_date and (previous_record is None or item_date > previous_record.get("date", "")):
                        previous_record = item
                
                if previous_record:
                    previous_net_value = previous_record["net_value"]
                    category_profit[category] += shares * (net_value - previous_net_value)
                elif "change" in nv and nv["change"] != 0:
                    change_pct = nv["change"] / 100
                    if change_pct != -1:
                        market_value = shares * net_value
                        yesterday_value = market_value / (1 + change_pct)
                        category_profit[category] += market_value - yesterday_value
    
    return category_profit