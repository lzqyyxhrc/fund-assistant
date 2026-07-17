import streamlit as st
from components.index_chart import render_index_comparison_chart, get_index_performance, get_portfolio_performance


def render_index_analysis():
    st.header("📈 指数对比分析")
    
    index_chart = render_index_comparison_chart()
    if index_chart:
        st.plotly_chart(index_chart, width='stretch')
        
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
    
    st.divider()
    
    st.subheader("📊 下载指数数据")
    
    if st.button("🔄 下载指数数据", type="primary"):
        from components.index_chart import download_index_data
        with st.spinner("正在下载指数数据..."):
            download_index_data()
        st.success("指数数据下载完成！")
        st.rerun()