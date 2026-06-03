import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import math
from services.storage import get_category_names, get_category_color

def calculate_fund_metrics(fund_code, net_value_history, time_range="成立以来"):
    """计算基金的年化收益、最大回撤和夏普比率
    
    Args:
        fund_code: 基金代码
        net_value_history: 净值历史数据
        time_range: 时间范围，"今年以来" 或 "成立以来"
    
    Returns:
        dict: 包含 annualized_return, max_drawdown, sharpe_ratio 的字典
    """
    if fund_code not in net_value_history:
        return {
            "annualized_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None
        }
    
    history_data = net_value_history[fund_code]
    
    dates = []
    net_values = []
    
    for date_key, data in history_data.items():
        actual_date = data.get("date", date_key)
        dates.append(actual_date)
        net_values.append(data.get("net_value", 0))
    
    if len(net_values) < 2:
        return {
            "annualized_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None
        }
    
    # 按日期排序
    sorted_indices = sorted(range(len(dates)), key=lambda i: dates[i])
    dates = [dates[i] for i in sorted_indices]
    net_values = [net_values[i] for i in sorted_indices]
    
    # 根据时间范围过滤
    if time_range == "今年以来":
        from datetime import datetime
        current_year = datetime.now().year
        year_start = f"{current_year}-01-01"
        
        filtered_indices = [i for i, date in enumerate(dates) if date >= year_start]
        if not filtered_indices:
            return {
                "annualized_return": None,
                "max_drawdown": None,
                "sharpe_ratio": None
            }
        net_values = [net_values[i] for i in filtered_indices]
    
    # 计算简单日收益率
    daily_returns = []
    for i in range(1, len(net_values)):
        ret = (net_values[i] - net_values[i-1]) / net_values[i-1]
        daily_returns.append(ret)
    
    if len(daily_returns) < 2:
        return {
            "annualized_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None
        }
    
    # 计算年化收益 (CAGR)
    total_return = (net_values[-1] - net_values[0]) / net_values[0]
    days = len(daily_returns)
    years = days / 252  # 按252个交易日计算
    if years > 0 and total_return > -1:
        annualized_return = math.pow(1 + total_return, 1 / years) - 1
    else:
        annualized_return = None
    
    # 计算最大回撤
    max_dd = 0.0
    peak = net_values[0]
    for nv in net_values:
        if nv > peak:
            peak = nv
        drawdown = (peak - nv) / peak
        if drawdown > max_dd:
            max_dd = drawdown
    
    # 计算夏普比率
    # 无风险利率设为3%（年化）
    risk_free_rate = 0.03
    
    # 计算日收益率均值和标准差
    mean_daily = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_daily) ** 2 for r in daily_returns) / (len(daily_returns) - 1)  # 样本标准差
    std_daily = math.sqrt(variance)
    
    if std_daily > 0:
        # 年化收益率（简单收益率年化）
        annual_return_simple = mean_daily * 252
        annual_volatility = std_daily * math.sqrt(252)
        
        # 夏普比率 = (年化收益率 - 无风险利率) / 年化波动率
        sharpe_ratio = (annual_return_simple - risk_free_rate) / annual_volatility
    else:
        sharpe_ratio = None
    
    return {
        "annualized_return": annualized_return,
        "max_drawdown": max_dd,
        "sharpe_ratio": sharpe_ratio
    }

def render_pie_chart(category_values, targets):
    category_names = get_category_names()
    
    labels = [category_names[k] for k in category_values.keys()]
    values = list(category_values.values())
    colors = [get_category_color(k) for k in category_values.keys()]
    
    fig = px.pie(
        values=values,
        names=labels,
        color_discrete_sequence=colors,
        hole=0.4,
        title="当前资产分布"
    )
    
    fig.update_layout(
        margin=dict(t=50, b=10, l=10, r=10),
        height=300
    )
    
    return fig

def render_bar_chart(current_weights, targets):
    category_names = get_category_names()
    
    categories = list(current_weights.keys())
    current_values = [current_weights[k] * 100 for k in categories]
    target_values = [targets[k] * 100 for k in categories]
    
    fig = go.Figure(data=[
        go.Bar(name='当前仓位', x=[category_names[k] for k in categories], y=current_values, marker_color='#1E90FF'),
        go.Bar(name='目标仓位', x=[category_names[k] for k in categories], y=target_values, marker_color='#FF6347')
    ])
    
    fig.update_layout(
        barmode='group',
        title="当前仓位 vs 目标仓位",
        yaxis=dict(title='仓位比例 (%)'),
        margin=dict(t=50, b=10, l=10, r=10),
        height=300
    )
    
    return fig

def render_gauge_chart(category, current_weight, target_weight):
    category_names = get_category_names()
    color = get_category_color(category)
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=current_weight * 100,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': category_names[category], 'font': {'size': 14}},
        number={'font': {'size': 22}, 'suffix': '%'},
        delta={'reference': target_weight * 100, 'increasing': {'color': "#32CD32"}, 'decreasing': {'color': "#FF6347"}, 'font': {'size': 14}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickfont': {'size': 10}},
            'bar': {'color': color, 'thickness': 0.4},
            'steps': [
                {'range': [0, 30], 'color': "#FFE4E1"},
                {'range': [30, 70], 'color': "#E0FFE0"},
                {'range': [70, 100], 'color': "#FFE4E1"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 2},
                'thickness': 0.75,
                'value': target_weight * 100
            }
        }
    ))
    
    fig.update_layout(
        height=220,
        margin=dict(t=40, b=20, l=10, r=10),
        showlegend=False
    )
    
    return fig

def render_fund_net_value_chart(fund_code, fund_name, net_value_history, time_range="今年以来"):
    """渲染单个基金净值走势图，支持时间范围选择
    
    Args:
        fund_code: 基金代码
        fund_name: 基金名称
        net_value_history: 净值历史数据
        time_range: 时间范围，"今年以来" 或 "成立以来"
    """
    if fund_code not in net_value_history:
        return None
    
    history_data = net_value_history[fund_code]
    
    dates = []
    net_values = []
    
    for date_key, data in history_data.items():
        actual_date = data.get("date", date_key)
        dates.append(actual_date)
        net_values.append(data.get("net_value", 0))
    
    if not dates:
        return None
    
    sorted_indices = sorted(range(len(dates)), key=lambda i: dates[i])
    dates = [dates[i] for i in sorted_indices]
    net_values = [net_values[i] for i in sorted_indices]
    
    if time_range == "今年以来":
        from datetime import datetime
        current_year = datetime.now().year
        year_start = f"{current_year}-01-01"
        
        filtered_dates = []
        filtered_net_values = []
        
        for i, date in enumerate(dates):
            if date >= year_start:
                filtered_dates.append(date)
                filtered_net_values.append(net_values[i])
        
        if not filtered_dates:
            return None
        
        dates = filtered_dates
        net_values = filtered_net_values
    
    # 计算移动平均线（在采样前计算以保证准确性）
    ma120 = []
    ma250 = []
    
    # MA120 - 120日均线
    if len(net_values) >= 120:
        for i in range(len(net_values)):
            if i < 119:
                ma120.append(None)
            else:
                ma120.append(sum(net_values[i-119:i+1]) / 120)
    
    # MA250 - 250日均线
    if len(net_values) >= 250:
        for i in range(len(net_values)):
            if i < 249:
                ma250.append(None)
            else:
                ma250.append(sum(net_values[i-249:i+1]) / 250)
    
    # 根据数据量动态调整采样频率
    total_points = len(dates)
    if total_points <= 60:
        # 数据量较少（约2个月），不采样
        sample_interval = 1
    elif total_points <= 120:
        # 数据量适中（约4个月），间隔2采样
        sample_interval = 2
    elif total_points <= 250:
        # 数据量较多（约1年），间隔5采样
        sample_interval = 5
    elif total_points <= 500:
        # 数据量很多（约2年），间隔10采样
        sample_interval = 10
    else:
        # 数据量非常大（超过2年），间隔20采样
        sample_interval = 20
    
    # 进行采样
    dates = dates[::sample_interval]
    net_values = net_values[::sample_interval]
    
    # 均线也要同步采样
    if ma120:
        ma120 = ma120[::sample_interval]
    if ma250:
        ma250 = ma250[::sample_interval]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=dates,
        y=net_values,
        mode='lines+markers',
        name='单位净值',
        line=dict(color='#1E90FF', width=2),
        marker=dict(size=6)
    ))
    
    # 添加MA120
    if ma120 and any(v is not None for v in ma120):
        fig.add_trace(go.Scatter(
            x=dates,
            y=ma120,
            mode='lines',
            name='MA120',
            line=dict(color='#32CD32', width=1.5, dash='dash'),
            opacity=0.8
        ))
    
    # 添加MA250
    if ma250 and any(v is not None for v in ma250):
        fig.add_trace(go.Scatter(
            x=dates,
            y=ma250,
            mode='lines',
            name='MA250',
            line=dict(color='#FFD700', width=1.5, dash='dash'),
            opacity=0.8
        ))
    
    # 计算所选时间范围的涨跌幅
    if len(net_values) >= 2:
        period_return = ((net_values[-1] - net_values[0]) / net_values[0] * 100)
        title_suffix = f"（{time_range}: {period_return:+.2f}%）"
    else:
        title_suffix = ""
    
    fig.update_layout(
        title={
            'text': f"{fund_name} ({fund_code}) {title_suffix}",
            'font': {'size': 14}
        },
        xaxis=dict(
            title='日期',
            tickangle=-45,
            tickformat='%m-%d',
            tickvals=dates,
            type='category'
        ),
        yaxis=dict(
            title='单位净值',
            side='left',
            tickformat='.4f'
        ),
        margin=dict(t=50, b=50, l=50, r=50),
        height=300,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        hovermode='x unified'
    )
    
    return fig