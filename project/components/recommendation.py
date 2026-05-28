import streamlit as st
from services.calculator import calculate_rebalancing_amounts, distribute_amount_to_funds, calculate_deviation, is_rebalance_needed, DEFAULT_REBALANCE_THRESHOLD
from services.storage import get_category_names, get_category_color

def render_recommendation(targets, category_values, total_value, new_investment, funds, net_values):
    st.header("💡 今日定投建议")

    if new_investment <= 0:
        st.info("请在左侧输入定投金额")
        return

    threshold = st.session_state.get("rebalance_threshold", DEFAULT_REBALANCE_THRESHOLD)

    current_weights = {k: (category_values.get(k, 0) / total_value) if total_value > 0 else 0 for k in targets.keys()}
    deviations = calculate_deviation(current_weights, targets)
    need_rebalance = is_rebalance_needed(deviations, threshold)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("偏离度状态")
        if need_rebalance:
            st.warning(f"⚠️ 偏离度超过 ±{threshold*100:.1f}%，触发再平衡定投策略")
        else:
            st.info(f"✅ 偏离度在 ±{threshold*100:.1f}% 以内，按目标比例定投")
    with col2:
        st.metric("偏离阈值", f"±{threshold*100:.1f}%")

    st.divider()

    rebal_amounts = calculate_rebalancing_amounts(targets, category_values, total_value, new_investment, threshold)

    st.subheader("大类资产分配")

    total_allocated = sum(rebal_amounts.values())

    for category in ["nasdaq", "dividend", "gold"]:
        amount = rebal_amounts.get(category, 0)
        target_pct = targets.get(category, 0) * 100
        current_pct = (category_values.get(category, 0) / total_value * 100) if total_value > 0 else 0
        deviation_pct = deviations.get(category, 0) * 100

        color = get_category_color(category)
        category_name = get_category_names()[category]

        deviation_indicator = ""
        if deviation_pct > threshold * 100:
            deviation_indicator = "📈 超配"
        elif deviation_pct < -threshold * 100:
            deviation_indicator = "📉 低配"
        else:
            deviation_indicator = "⚖️ 均衡"

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.write(f"**{category_name}** {deviation_indicator}")
            st.write(f"目标: {target_pct:.1f}% | 当前: {current_pct:.1f}% | 偏离: {deviation_pct:+.1f}%")
        with col2:
            st.metric("", f"¥{amount:,.2f}")
        with col3:
            st.write("")
            if abs(deviation_pct) > threshold * 100:
                priority_text = "优先" if deviation_pct < 0 else "减投"
                st.caption(f"**{priority_text}**")

        progress = amount / new_investment if new_investment > 0 else 0
        st.progress(min(max(progress, 0.0), 1.0))

    st.divider()

    st.subheader("基金级分配明细")

    for category in ["nasdaq", "dividend", "gold"]:
        amount = rebal_amounts.get(category, 0)
        if amount > 0:
            fund_list = funds.get(category, [])
            allocations = distribute_amount_to_funds(amount, fund_list, net_values)

            with st.expander(f"{get_category_names()[category]} - ¥{amount:,.2f}"):
                if allocations:
                    data = []
                    for alloc in allocations:
                        data.append({
                            "基金名称": alloc["name"],
                            "基金代码": alloc["code"],
                            "分配金额": f"¥{alloc['amount']:,.2f}",
                            "可买份额": f"{alloc['shares']:.2f}",
                            "当前净值": f"¥{alloc['net_value']:.4f}"
                        })
                    st.dataframe(data)
                else:
                    st.write("该类别下暂无基金")

    st.divider()

    st.subheader("再平衡效果预估")
    col1, col2 = st.columns(2)

    with col1:
        st.write("**定投前仓位:**")
        for category in ["nasdaq", "dividend", "gold"]:
            pct = (category_values.get(category, 0) / total_value * 100) if total_value > 0 else 0
            deviation = deviations.get(category, 0) * 100
            st.write(f"- {get_category_names()[category]}: {pct:.1f}% ({deviation:+.1f}%)")

    with col2:
        st.write("**定投后预估仓位:**")
        new_total = total_value + new_investment
        for category in ["nasdaq", "dividend", "gold"]:
            new_value = category_values.get(category, 0) + rebal_amounts.get(category, 0)
            pct = (new_value / new_total * 100) if new_total > 0 else 0
            target_pct = targets.get(category, 0) * 100
            st.write(f"- {get_category_names()[category]}: {pct:.1f}% → {target_pct:.1f}%")