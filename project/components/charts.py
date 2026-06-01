import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from services.storage import get_category_names, get_category_color

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

def render_fund_net_value_chart(fund_code, fund_name, net_value_history):
    """渲染单个基金今年以来的净值走势图"""
    if fund_code not in net_value_history:
        return None
    
    history_data = net_value_history[fund_code]
    
    from datetime import datetime
    year_start = datetime.now().strftime("%Y-01-01")
    
    dates = []
    net_values = []
    changes = []
    
    for date_key, data in history_data.items():
        actual_date = data.get("date", date_key)
        if actual_date >= year_start:
            dates.append(actual_date)
            net_values.append(data.get("net_value", 0))
            changes.append(data.get("change", 0))
    
    if not dates:
        return None
    
    sorted_indices = sorted(range(len(dates)), key=lambda i: dates[i])
    dates = [dates[i] for i in sorted_indices]
    net_values = [net_values[i] for i in sorted_indices]
    changes = [changes[i] for i in sorted_indices]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=dates,
        y=net_values,
        mode='lines+markers',
        name='单位净值',
        line=dict(color='#1E90FF', width=2),
        marker=dict(size=6)
    ))
    
    fig.add_trace(go.Scatter(
        x=dates,
        y=changes,
        mode='lines+markers',
        name='日涨幅(%)',
        yaxis='y2',
        line=dict(color='#FF6347', width=1, dash='dot'),
        marker=dict(size=4)
    ))
    
    # 计算今年以来的涨跌幅
    if len(net_values) >= 2:
        year_return = ((net_values[-1] - net_values[0]) / net_values[0] * 100)
        title_suffix = f"（今年以来: {year_return:+.2f}%）"
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
        yaxis2=dict(
            title='日涨幅(%)',
            side='right',
            overlaying='y',
            tickformat='.2f',
            showgrid=False
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