import streamlit as st
from components.charts import render_pie_chart, render_bar_chart, render_gauge_chart
from services.storage import get_category_names, get_category_color
from services.fund_fetcher import check_data_freshness

def render_dashboard(category_values, current_weights, targets, net_values):
    total_value = sum(category_values.values())

    total_cost, total_profit, total_profit_pct = calculate_total_profit(st.session_state.config, net_values)

    freshness = check_data_freshness(net_values)
    if not freshness["all_fresh"]:
        st.warning(f"警告: 部分数据来自历史缓存（实时:{freshness['fresh']} | 缓存:{freshness['cached']}），仅供参考")

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