import streamlit as st
import json
import os
from components.charts import render_pie_chart, render_bar_chart, render_gauge_chart, render_fund_net_value_chart, calculate_fund_metrics
from services.storage import get_category_names, get_category_color
from services.fund_fetcher import check_data_freshness

NET_VALUE_HISTORY_PATH = "net_value_history.json"

def load_net_value_history():
    """加载净值历史数据"""
    if os.path.exists(NET_VALUE_HISTORY_PATH):
        with open(NET_VALUE_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def render_dashboard(category_values, current_weights, targets, net_values):
    total_value = sum(category_values.values())

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
        st.metric("总资产", f"¥{total_value:,.2f}")
    with col2:
        st.metric("持仓成本", f"¥{total_cost:,.2f}")
    with col3:
        st.metric("持仓收益", f"¥{total_profit:,.2f}", delta=f"{total_profit_pct:.2f}%", delta_color="normal" if total_profit >= 0 else "inverse")
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
                st.write(f"市值: ¥{category_market[category]:,.2f}")
                st.write(f"成本: ¥{category_cost[category]:,.2f}")
                profit_color = "green" if category_profit[category] >= 0 else "red"
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
    elif has_cache_data and yesterday_profit == 0.0:
        # 有缓存数据但收益为0，可能是真的收益为0
        st.info("部分基金使用缓存数据，收益计算可能不完整")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("昨日收益金额", f"¥{yesterday_profit:,.2f}", delta=f"{yesterday_profit_pct:.2f}%", delta_color="normal" if yesterday_profit >= 0 else "inverse")
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
                profit_text = "<br>".join([f"{category_names[k]}: {'+' if v >= 0 else ''}¥{v:,.2f}" for k, v in category_yesterday_profit.items()])
                st.markdown(f"**各类资产收益：**<br>{profit_text}", unsafe_allow_html=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(render_pie_chart(category_values, targets), use_container_width=True)
    with col2:
        st.plotly_chart(render_bar_chart(current_weights, targets), use_container_width=True)
    
    st.divider()
    
    st.subheader("仓位偏离度")
    col1, col2, col3 = st.columns(3)
    
    categories = ["nasdaq", "dividend", "gold"]
    for i, category in enumerate(categories):
        with [col1, col2, col3][i]:
            current_weight = current_weights.get(category, 0) if isinstance(current_weights, dict) else 0
            target_weight = targets.get(category, 0) if isinstance(targets, dict) else 0
            st.plotly_chart(
                render_gauge_chart(category, current_weight, target_weight),
                use_container_width=True
            )
    
    st.divider()
    
    st.subheader("持仓明细")
    category_names = get_category_names()
    
    # 加载净值历史数据用于计算指标
    net_value_history = load_net_value_history()
    
    for category in ["nasdaq", "dividend", "gold"]:
        with st.expander(f"{category_names[category]}"):
            funds = st.session_state.config["funds"].get(category, [])
            if funds:
                data = []
                for fund in funds:
                    if fund["code"] in net_values:
                        nv = net_values[fund["code"]]
                        cost_price = fund.get("cost_price", 0.0)
                        shares = fund.get("shares", 0.0)
                        pending_amount = fund.get("pending_amount", 0.0)
                        
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
                st.dataframe(data)
                
                # 显示待确认金额提示
                has_pending = any(f.get("pending_amount", 0) > 0 for f in funds)
                if has_pending:
                    st.info("部分金额处于待确认状态，T+2个交易日后自动确认（份额=待确认金额/确认日净值），不参与当前市值计算")
            else:
                st.write("暂无持仓")
    
    st.divider()
    
    st.subheader("📈 基金净值走势")
    
    # 添加更新历史净值按钮
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 更新历史数据", use_container_width=True):
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
                    st.plotly_chart(chart, use_container_width=True)
                else:
                    st.info(f"基金 {fund['code']} 在所选时间范围内暂无净值数据")

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
    """计算昨日收益（基于净值日涨幅）
    
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
    total_value = 0.0
    valid_data_value = 0.0  # 使用有效数据计算的市值
    
    for category in ["nasdaq", "dividend", "gold"]:
        funds = config["funds"].get(category, [])
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                shares = fund["shares"]
                net_value = nv["net_value"]
                
                # 检查数据新鲜度
                data_date = nv.get("date", "")
                
                # 根据基金类型判断数据是否可用
                # 纳指QDII基金：允许今天、昨天、前天的数据（因为时差原因）
                # A股基金：允许今天、昨天的数据
                is_valid = False
                if category == "nasdaq":
                    is_valid = (data_date == today or data_date == yesterday or data_date == day_before_yesterday)
                else:
                    is_valid = (data_date == today or data_date == yesterday)
                
                if not is_valid:
                    continue
                
                change_pct = nv["change"] / 100  # 转换为小数
                
                # 计算当前市值
                market_value = shares * net_value
                total_value += market_value
                valid_data_value += market_value
                
                # 计算昨日收益：假设当前市值是今日收盘后的值
                # 昨日市值 = 当前市值 / (1 + 日涨幅)
                # 昨日收益 = 当前市值 - 昨日市值
                if change_pct != -1:
                    yesterday_value = market_value / (1 + change_pct)
                    yesterday_profit += market_value - yesterday_value
    
    # 只有有效数据才计算收益率
    if valid_data_value > 0:
        yesterday_profit_pct = (yesterday_profit / (valid_data_value - yesterday_profit)) * 100
    
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
    """计算各类资产的昨日收益"""
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
                
                # 检查数据新鲜度
                data_date = nv.get("date", "")
                
                # 根据基金类型判断数据是否可用
                # 纳指QDII基金：允许今天、昨天、前天的数据（因为时差原因）
                # A股基金：允许今天、昨天的数据
                is_valid = False
                if category == "nasdaq":
                    is_valid = (data_date == today or data_date == yesterday or data_date == day_before_yesterday)
                else:
                    is_valid = (data_date == today or data_date == yesterday)
                
                if not is_valid:
                    continue
                
                change_pct = nv["change"] / 100
                
                market_value = shares * net_value
                if change_pct != -1:
                    yesterday_value = market_value / (1 + change_pct)
                    category_profit[category] += market_value - yesterday_value
    
    return category_profit