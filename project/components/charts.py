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