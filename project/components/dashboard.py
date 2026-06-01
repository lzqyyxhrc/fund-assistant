import streamlit as st
import json
import os
from components.charts import render_pie_chart, render_bar_chart, render_gauge_chart, render_fund_net_value_chart
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
    
    st.subheader("💰 昨日收益")
    
    # 检查是否有缓存数据
    freshness = check_data_freshness(net_values)
    has_cache_data = not freshness["all_fresh"]
    
    if has_cache_data and yesterday_profit == 0.0 and yesterday_profit_pct == 0.0:
        # 全部数据都是缓存，无法计算昨日收益
        st.info("ℹ️ 当前净值数据来自历史缓存，昨日收益暂不可用")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("昨日收益金额", f"¥{yesterday_profit:,.2f}", delta=f"{yesterday_profit_pct:.2f}%", delta_color="normal" if yesterday_profit >= 0 else "inverse")
        with col2:
            # 计算各类资产的昨日收益
            category_yesterday_profit = calculate_category_yesterday_profit(st.session_state.config, net_values)
            category_names = get_category_names()
            
            # 检查是否有有效数据
            if sum(category_yesterday_profit.values()) == 0.0 and has_cache_data:
                st.info("ℹ️ 部分基金使用缓存数据，相关资产类别的昨日收益暂不可用")
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
    
    for category in ["nasdaq", "dividend", "gold"]:
        with st.expander(f"{category_names[category]}"):
            funds = st.session_state.config["funds"].get(category, [])
            if funds:
                data = []
                for fund in funds:
                    if fund["code"] in net_values:
                        nv = net_values[fund["code"]]
                        cost_price = fund.get("cost_price", 0.0)
                        market_value = fund["shares"] * nv["net_value"]
                        cost_value = fund["shares"] * cost_price if cost_price > 0 else 0
                        profit = market_value - cost_value
                        profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0
                        
                        net_value_str = f"¥{nv['net_value']:.4f}"
                        if "date" in nv:
                            from datetime import datetime
                            today = datetime.now().strftime("%Y-%m-%d")
                            if nv["date"] != today:
                                net_value_str += f" ({nv['date']})"
                        
                        data.append({
                            "基金名称": fund["name"],
                            "基金代码": fund["code"],
                            "持有份额": f"{fund['shares']:.2f}",
                            "成本价": f"¥{cost_price:.3f}",
                            "最新净值": net_value_str,
                            "日涨幅": f"{nv['change']:.2f}%",
                            "持仓市值": f"¥{market_value:,.2f}",
                            "持仓成本": f"¥{cost_value:,.2f}",
                            "盈亏金额": f"¥{profit:,.2f}",
                            "盈亏比例": f"{profit_pct:.2f}%"
                        })
                st.dataframe(data)
            else:
                st.write("暂无持仓")
    
    st.divider()
    
    st.subheader("📊 基金净值走势（今年以来）")
    
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
            
            st.success("✅ 历史净值更新完成！")
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
            selected_fund = st.selectbox(
                "选择基金查看净值走势",
                options=range(len(all_funds)),
                format_func=lambda i: f"{all_funds[i]['name']} ({all_funds[i]['code']})"
            )
            
            if selected_fund is not None:
                fund = all_funds[selected_fund]
                chart = render_fund_net_value_chart(fund["code"], fund["name"], net_value_history)
                
                if chart:
                    st.plotly_chart(chart, use_container_width=True)
                else:
                    st.info(f"基金 {fund['code']} 暂无今年以来的净值数据")

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
    
    注意：仅当净值数据为最新时才计算，缓存数据不参与计算以避免错误
    """
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
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
                
                # 检查数据新鲜度：只有今日数据或最新数据才参与计算
                data_date = nv.get("date", "")
                source = nv.get("source", "")
                
                # 如果是缓存数据（非今日），跳过计算
                if data_date != today and source in ["cache", "cache_fallback"]:
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

def calculate_category_yesterday_profit(config, net_values):
    """计算各类资产的昨日收益（仅使用最新数据）"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
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
                source = nv.get("source", "")
                
                # 如果是缓存数据（非今日），跳过计算
                if data_date != today and source in ["cache", "cache_fallback"]:
                    continue
                
                change_pct = nv["change"] / 100
                
                market_value = shares * net_value
                if change_pct != -1:
                    yesterday_value = market_value / (1 + change_pct)
                    category_profit[category] += market_value - yesterday_value
    
    return category_profit