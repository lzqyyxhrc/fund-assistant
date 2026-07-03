import streamlit as st
from components.charts import render_pie_chart, render_bar_chart
from services.storage import get_category_names, get_category_color
from services.fund_fetcher import check_data_freshness
from services.net_value_storage import get_fund_history_data


def format_money(amount, pattern="¥{:,.2f}"):
    if st.session_state.get("privacy_mode", False):
        return "****"
    return pattern.format(amount)


def calculate_total_profit(config, net_values):
    total_cost = 0
    total_market = 0
    for category in ["nasdaq", "dividend", "gold"]:
        for fund in config["funds"].get(category, []):
            if fund["code"] in net_values:
                shares = fund.get("shares", 0)
                cost_price = fund.get("cost_price", 0)
                total_cost += shares * cost_price
                total_market += shares * net_values[fund["code"]]["net_value"]
    profit = total_market - total_cost
    profit_pct = (profit / total_cost * 100) if total_cost > 0 else 0
    return total_cost, profit, profit_pct


def calculate_yesterday_profit(config, net_values):
    """按最新净值日与前一个交易日净值差计算昨日收益。"""
    total_yesterday_profit = 0.0
    valid_data_value = 0.0

    for category in ["nasdaq", "dividend", "gold"]:
        for fund in config["funds"].get(category, []):
            code = fund.get("code")
            if code not in net_values:
                continue

            shares = fund.get("shares", 0)
            nv = net_values[code]
            net_value = nv.get("net_value")
            data_date = nv.get("date", "")
            if not net_value or not data_date:
                continue

            previous_record = None
            for item in get_fund_history_data(code).values():
                item_date = item.get("date", "")
                if item_date < data_date and (previous_record is None or item_date > previous_record.get("date", "")):
                    previous_record = item

            if previous_record:
                previous_net_value = previous_record["net_value"]
                total_yesterday_profit += shares * (net_value - previous_net_value)
                valid_data_value += shares * net_value
            elif "change" in nv and nv["change"] != 0:
                change_pct = nv["change"] / 100
                if change_pct != -1:
                    market_value = shares * net_value
                    yesterday_value = market_value / (1 + change_pct)
                    total_yesterday_profit += market_value - yesterday_value
                    valid_data_value += market_value

    if valid_data_value <= 0:
        return 0.0, 0.0

    denominator = valid_data_value - total_yesterday_profit
    profit_pct = (total_yesterday_profit / denominator * 100) if denominator > 0 else 0.0
    return total_yesterday_profit, profit_pct


def calculate_category_total_profit(config, net_values):
    category_cost = {"nasdaq": 0, "dividend": 0, "gold": 0}
    category_market = {"nasdaq": 0, "dividend": 0, "gold": 0}
    category_profit = {"nasdaq": 0, "dividend": 0, "gold": 0}
    category_profit_pct = {"nasdaq": 0, "dividend": 0, "gold": 0}
    
    for category in ["nasdaq", "dividend", "gold"]:
        for fund in config["funds"].get(category, []):
            if fund["code"] in net_values:
                shares = fund.get("shares", 0)
                cost_price = fund.get("cost_price", 0)
                category_cost[category] += shares * cost_price
                category_market[category] += shares * net_values[fund["code"]]["net_value"]
    
    for category in ["nasdaq", "dividend", "gold"]:
        category_profit[category] = category_market[category] - category_cost[category]
        category_profit_pct[category] = (category_profit[category] / category_cost[category] * 100) if category_cost[category] > 0 else 0
    
    return category_cost, category_market, category_profit, category_profit_pct


def calculate_category_yesterday_profit(config, net_values):
    result = {"nasdaq": 0.0, "dividend": 0.0, "gold": 0.0}
    for category in ["nasdaq", "dividend", "gold"]:
        for fund in config["funds"].get(category, []):
            code = fund.get("code")
            if code not in net_values:
                continue

            shares = fund.get("shares", 0)
            nv = net_values[code]
            net_value = nv.get("net_value")
            data_date = nv.get("date", "")
            if not net_value or not data_date:
                continue

            previous_record = None
            for item in get_fund_history_data(code).values():
                item_date = item.get("date", "")
                if item_date < data_date and (previous_record is None or item_date > previous_record.get("date", "")):
                    previous_record = item

            if previous_record:
                result[category] += shares * (net_value - previous_record["net_value"])
            elif "change" in nv and nv["change"] != 0:
                change_pct = nv["change"] / 100
                if change_pct != -1:
                    market_value = shares * net_value
                    yesterday_value = market_value / (1 + change_pct)
                    result[category] += market_value - yesterday_value
    return result


def render_dashboard():
    config = st.session_state.config
    net_values = st.session_state.net_values
    targets = st.session_state.targets
    
    category_values = {}
    current_weights = {}
    for category in ["nasdaq", "dividend", "gold"]:
        category_values[category] = sum(
            fund.get("shares", 0) * net_values.get(fund["code"], {}).get("net_value", 0)
            for fund in config["funds"].get(category, [])
        )
    
    total_value = sum(category_values.values())
    if total_value > 0:
        for category in ["nasdaq", "dividend", "gold"]:
            current_weights[category] = category_values[category] / total_value
    else:
        current_weights = {"nasdaq": 0, "dividend": 0, "gold": 0}

    privacy_col, _ = st.columns([1, 4])
    with privacy_col:
        st.session_state["privacy_mode"] = st.toggle("🔒 隐私模式", value=st.session_state.get("privacy_mode", False))

    total_cost, total_profit, total_profit_pct = calculate_total_profit(config, net_values)
    yesterday_profit, yesterday_profit_pct = calculate_yesterday_profit(config, net_values)

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
        st.metric("基金数量", sum(len(funds) for funds in config["funds"].values()))
    
    st.subheader("各类资产总收益")
    
    category_cost, category_market, category_profit, category_profit_pct = calculate_category_total_profit(config, net_values)
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
    
    freshness = check_data_freshness(net_values)
    has_cache_data = not freshness["all_fresh"]
    
    has_valid_data = False
    for category in ["nasdaq", "dividend", "gold"]:
        funds = config["funds"].get(category, [])
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
        st.info("当前净值数据过于陈旧，无法计算昨日收益")
    else:
        if has_cache_data:
            st.caption("部分基金使用缓存数据，昨日收益按可用历史净值估算")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("昨日收益金额", format_money(yesterday_profit), delta=f"{yesterday_profit_pct:.2f}%", delta_color="normal" if yesterday_profit >= 0 else "inverse")
        with col2:
            category_yesterday_profit = calculate_category_yesterday_profit(config, net_values)
            category_names = get_category_names()
            
            if sum(category_yesterday_profit.values()) == 0.0:
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
        st.subheader("资产配置饼图")
        st.plotly_chart(render_pie_chart(category_values, targets), width='stretch')
    with col2:
        st.subheader("配置对比柱状图")
        st.plotly_chart(render_bar_chart(current_weights, targets), width='stretch')
    
    st.divider()
    
    st.subheader("⚡ 快捷操作")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔄 刷新净值数据", type="primary"):
            from services.fund_fetcher import get_fund_batch_net_value
            all_codes = []
            for category in ["nasdaq", "dividend", "gold"]:
                for fund in config["funds"].get(category, []):
                    if fund["code"]:
                        all_codes.append(fund["code"])
            if all_codes:
                with st.spinner("正在获取最新净值..."):
                    st.session_state.net_values = get_fund_batch_net_value(all_codes)
                st.success("净值数据已更新！")
                st.rerun()
    with col2:
        if st.button("📊 更新估值评分", type="primary"):
            from services.valuation_fetcher import update_all_valuation_data
            with st.spinner("正在更新估值数据..."):
                update_all_valuation_data()
            st.success("估值数据已更新！")
    with col3:
        if st.button("📝 生成日报", type="primary"):
            from daily_report import generate_daily_report
            with st.spinner("正在生成日报..."):
                report_path = generate_daily_report()
            if report_path:
                st.success(f"日报已生成：{report_path}")
            else:
                st.warning("生成日报失败，请检查日志")