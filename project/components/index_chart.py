"""
指数对比图组件
用于在Streamlit看板中展示纳斯达克100、中证红利、黄金三大指数的对比
支持定投策略回测
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
from services.database import has_index_prices, import_index_csv, load_index_prices

def load_index_data(data_dir="data/index"):
    """加载所有指数数据"""
    indices = {
        "NDX": {"name": "纳斯达克100", "color": "#1E90FF"},
        "000922": {"name": "中证红利净收益", "color": "#32CD32"},
        "AU9999": {"name": "黄金", "color": "#FFD700"}
    }

    data = {}
    for code, info in indices.items():
        df = _load_single_index(code, data_dir)
        if df is not None:
            data[code] = {
                "name": info["name"],
                "color": info["color"],
                "df": df
            }

    return data


def _load_single_index(index_code, data_dir="data/index"):
    """从数据库加载单个指数数据；数据库为空时从CSV导入一次"""
    if not has_index_prices(index_code):
        if not os.path.exists(data_dir):
            return None

        files = [f for f in os.listdir(data_dir) if f.startswith(index_code) and f.endswith('.csv')]
        if not files:
            return None

        total_return_files = [f for f in files if 'total_return' in f or '全收益' in f]
        if total_return_files:
            latest_file = sorted(total_return_files)[-1]
            print(f"[INFO] 导入全收益/前复权指数数据到数据库: {latest_file}")
        else:
            latest_file = sorted(files)[-1]
            print(f"[INFO] 导入价格指数数据到数据库: {latest_file}")

        import_index_csv(index_code, os.path.join(data_dir, latest_file))

    df = load_index_prices(index_code)
    if df.empty:
        return None

    return df


def backtest_dca_with_rebalancing(df, weights, threshold=0.05, monthly_investment=1000):
    """
    回测定投策略（带仓位再平衡）
    
    Args:
        df: DataFrame，包含各指数的标准化价格
        weights: dict，目标权重配置
        threshold: float，再平衡阈值（默认5%）
        monthly_investment: float，每月定投金额（默认1000元）
    
    Returns:
        portfolio_cumulative: 累计收益序列（总资产价值）
        rebalance_dates: 调仓日期列表
        investment_dates: 定投日期列表
        daily_returns: 排除定投影响的每日真实收益率
    """
    # 提取价格数据（排除date列）
    price_cols = [col for col in df.columns if col != 'date']
    prices = df[price_cols].copy()
    
    # 初始化持仓价值（初始为0）
    positions = pd.Series({k: 0.0 for k in weights.keys()})
    total_value = 0.0
    total_invested = 0.0
    
    portfolio_values = [0.0]
    rebalance_dates = []
    investment_dates = []
    daily_returns = []  # 记录排除定投影响的每日真实收益率
    
    # 计算每日收益率
    returns = prices.pct_change().fillna(0)
    
    # 记录上一个定投月份
    last_month = -1
    investment_dates_set = set()
    
    for i in range(len(df)):
        current_date = df.loc[i, 'date']
        current_month = current_date.month
        current_year = current_date.year
        
        # 如果不是第一天，更新资产价值并计算真实收益
        if i > 0:
            prev_total_value = portfolio_values[-1]
            
            # 更新各资产价值
            for code in weights.keys():
                if code in returns.columns:
                    positions[code] *= (1 + returns.loc[i, code])
            
            # 计算当前总资产价值（不包含本次定投）
            total_value_before_invest = positions.sum()
            
            # 计算真实收益率（排除定投影响）
            if prev_total_value > 0:
                true_return = (total_value_before_invest - prev_total_value) / prev_total_value
                daily_returns.append(true_return)
            else:
                daily_returns.append(0)
            
            total_value = total_value_before_invest
        else:
            daily_returns.append(0)  # 第一天没有收益
        
        # 每月第一天进行定投（简化处理：每月第一个交易日）
        if current_month != last_month or i == 0:
            # 按目标权重分配定投金额
            for code in weights.keys():
                positions[code] += monthly_investment * weights[code]
            total_invested += monthly_investment
            investment_dates.append(current_date)
            investment_dates_set.add(current_date)
            last_month = current_month
            # 重新计算总资产价值（因为定投后仓位变化了）
            total_value = positions.sum()
        
        # 计算当前仓位
        current_weights = positions / total_value if total_value > 0 else positions
        
        # 检查是否需要再平衡（只在定投日之后检查）
        if total_value > 0:
            need_rebalance = False
            for code, target_weight in weights.items():
                if code in current_weights:
                    deviation = abs(current_weights[code] - target_weight)
                    if deviation > threshold:
                        need_rebalance = True
                        break
            
            # 如果需要再平衡
            if need_rebalance:
                rebalance_dates.append(current_date)
                
                # 按目标权重重新分配
                for code in weights.keys():
                    positions[code] = total_value * weights[code]
        
        portfolio_values.append(total_value)
    
    # 转换为Series（去掉第一个0值）
    portfolio_cumulative = pd.Series(portfolio_values[1:], index=df['date'])
    # 转换收益率为Series
    daily_returns_series = pd.Series(daily_returns[1:], index=df['date'][1:])
    
    return portfolio_cumulative, rebalance_dates, investment_dates, total_invested, daily_returns_series


def render_index_comparison_chart():
    """生成指数对比图（Plotly格式），包含定投策略曲线"""
    data = load_index_data()

    if not data:
        return None

    # 对齐日期范围
    start_dates = []
    end_dates = []

    for code, info in data.items():
        df = info['df']
        start_dates.append(df['date'].min())
        end_dates.append(df['date'].max())

    common_start = max(start_dates)
    common_end = min(end_dates)

    # 创建图表
    fig = go.Figure()

    # 存储标准化后的数据用于计算投资组合
    normalized_data = {}

    # 添加每条指数曲线
    for code, info in data.items():
        df = info['df'].copy()
        df = df[(df['date'] >= common_start) & (df['date'] <= common_end)]
        df = df.sort_values('date').reset_index(drop=True)

        # 标准化处理（以第一天为基准）
        first_close = df['close'].iloc[0]
        df['normalized_close'] = df['close'] / first_close * 100

        normalized_data[code] = df

        # 添加曲线
        fig.add_trace(go.Scatter(
            x=df['date'],
            y=df['normalized_close'],
            name=info['name'],
            line=dict(color=info['color'], width=2),
            mode='lines',
            hovertemplate='%{x|%Y-%m-%d}<br>标准化净值: %{y:.2f}'
        ))

    # 计算投资组合策略（40%纳指 + 40%红利 + 20%黄金）
    weights = {
        "NDX": 0.4,    # 纳斯达克100
        "000922": 0.4, # 中证红利全收益
        "AU9999": 0.2  # 黄金
    }

    # 合并所有指数的标准化数据
    combined_df = None
    for code, df in normalized_data.items():
        if combined_df is None:
            combined_df = df[['date', 'normalized_close']].rename(columns={'normalized_close': code})
        else:
            combined_df = combined_df.merge(df[['date', 'normalized_close']], on='date', how='inner').rename(columns={'normalized_close': code})

    # 计算组合策略收益
    if combined_df is not None:
        combined_df = combined_df.sort_values('date').reset_index(drop=True)
        
        # 一次性买入组合：与指数曲线同口径，起点=100
        one_time_portfolio = sum(combined_df[code] * weight for code, weight in weights.items() if code in combined_df.columns)
        fig.add_trace(go.Scatter(
            x=combined_df['date'],
            y=one_time_portfolio,
            name='一次性组合 (40%纳指+40%红利+20%黄金)',
            line=dict(color='#8A2BE2', width=3),
            mode='lines',
            hovertemplate='%{x|%Y-%m-%d}<br>标准化净值: %{y:.2f}',
            legendrank=1
        ))
        
        # 策略1：定投（无再平衡）
        portfolio_cumulative_no_rebal, _, investment_dates_no_rebal, total_invested_no_rebal, _ = backtest_dca_with_rebalancing(
            combined_df, weights, threshold=1.0  # threshold=1.0表示永不平衡
        )
        
        # 将投资组合转换为收益率百分比（与指数保持一致的比例尺）
        # 计算累计投入曲线（每月投入1000元）
        monthly_investment = 1000
        investment_curve = []
        cumulative_invested = 0
        last_month = -1
        for i in range(len(combined_df)):
            current_month = combined_df.loc[i, 'date'].month
            if current_month != last_month or i == 0:
                cumulative_invested += monthly_investment
                last_month = current_month
            investment_curve.append(cumulative_invested)
        
        # 计算收益率（相对于累计投入），确保索引一致
        investment_series = pd.Series(investment_curve, index=combined_df['date'])
        portfolio_return_no_rebal = (portfolio_cumulative_no_rebal / investment_series) * 100
        
        # 添加定投（无再平衡）曲线（收益率形式）
        fig.add_trace(go.Scatter(
            x=combined_df['date'],
            y=portfolio_return_no_rebal,
            name=f'定投组合 (无再平衡，资产/累计投入) - 累计投入¥{total_invested_no_rebal:,.0f}',
            line=dict(color='#FF4444', width=3, dash='dash'),
            mode='lines',
            hovertemplate='%{x|%Y-%m-%d}<br>定投净值: %{y:.2f}<br>总资产: ¥%{portfolio_cumulative_no_rebal.loc[%{x}]:,.2f}',
            legendrank=2
        ))
        
        # 添加定投点标记
        if len(investment_dates_no_rebal) > 0:
            investment_indices = combined_df[combined_df['date'].isin(investment_dates_no_rebal)].index.tolist()
            investment_values_no_rebal = portfolio_return_no_rebal.iloc[investment_indices].tolist()
            fig.add_trace(go.Scatter(
                x=investment_dates_no_rebal,
                y=investment_values_no_rebal,
                name='定投点',
                mode='markers',
                marker=dict(color='#FF4444', size=6, symbol='circle'),
                hovertemplate='定投日期: %{x|%Y-%m-%d}<br>定投净值: %{y:.2f}',
                legendrank=5
            ))
        
        # 策略2：定投（带再平衡，偏差>5%时调仓）
        portfolio_cumulative_rebal, rebalance_dates, investment_dates_rebal, total_invested_rebal, _ = backtest_dca_with_rebalancing(
            combined_df, weights, threshold=0.05
        )
        
        # 计算策略2的收益率（相对于累计投入）
        portfolio_return_rebal = (portfolio_cumulative_rebal / investment_series) * 100
        
        # 添加定投（带再平衡）曲线（收益率形式）
        fig.add_trace(go.Scatter(
            x=combined_df['date'],
            y=portfolio_return_rebal,
            name=f'定投组合 (5%偏差再平衡，资产/累计投入) - 累计投入¥{total_invested_rebal:,.0f}',
            line=dict(color='#FF8C00', width=3, dash='dot'),
            mode='lines',
            hovertemplate='%{x|%Y-%m-%d}<br>定投净值: %{y:.2f}<br>总资产: ¥%{portfolio_cumulative_rebal.loc[%{x}]:,.2f}',
            legendrank=3
        ))
        
        # 添加调仓标记点
        if len(rebalance_dates) > 0:
            rebalance_indices = combined_df[combined_df['date'].isin(rebalance_dates)].index.tolist()
            rebalance_values = portfolio_return_rebal.iloc[rebalance_indices].tolist()
            fig.add_trace(go.Scatter(
                x=rebalance_dates,
                y=rebalance_values,
                name='调仓点',
                mode='markers',
                marker=dict(color='#FF8C00', size=10, symbol='triangle-up'),
                hovertemplate='调仓日期: %{x|%Y-%m-%d}<br>定投净值: %{y:.2f}',
                legendrank=4
            ))

    # 更新布局
    fig.update_layout(
        title={
            'text': f'指数走势对比与定投策略 ({common_start.date()} 至 {common_end.date()})',
            'x': 0.5,
            'y': 0.95,
            'font': {'size': 16, 'weight': 'bold'}
        },
        annotations=[dict(
            text='中证红利净收益指数数据来源：<a href="https://www.csindex.com.cn/#/indices/family/detail?indexCode=000922">中证指数官网</a>',
            showarrow=False,
            xref='paper', yref='paper',
            x=0.5, y=-0.45,
            font={'size': 10, 'color': '#666'},
            align='center'
        )],
        xaxis_title='日期',
        yaxis_title='标准化净值 / 定投净值（100为投入本金）',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=-0.35,
            xanchor='center',
            x=0.5
        ),
        hovermode='x unified',
        margin=dict(l=50, r=50, t=80, b=200),
        template='plotly_white'
    )

    # 添加网格线
    fig.update_xaxes(
        showgrid=True,
        gridcolor='lightgrey',
        tickformat='%Y-%m'
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor='lightgrey'
    )

    return fig


def get_index_performance():
    """获取指数表现数据"""
    data = load_index_data()

    if not data:
        return None

    # 对齐日期范围
    start_dates = []
    end_dates = []

    for code, info in data.items():
        df = info['df']
        start_dates.append(df['date'].min())
        end_dates.append(df['date'].max())

    common_start = max(start_dates)
    common_end = min(end_dates)

    performance = []

    for code, info in data.items():
        df = info['df'].copy()
        df = df[(df['date'] >= common_start) & (df['date'] <= common_end)]
        df = df.sort_values('date').reset_index(drop=True)

        # 计算指标
        first_close = df['close'].iloc[0]
        last_close = df['close'].iloc[-1]
        total_return = (last_close / first_close - 1) * 100

        # 计算年化收益率（时间加权）
        days = (df['date'].iloc[-1] - df['date'].iloc[0]).days
        annual_return = ((last_close / first_close) ** (365.25 / days) - 1) * 100 if days > 0 else 0

        returns = df['close'].pct_change().dropna()
        annual_volatility = returns.std() * (252 ** 0.5) * 100
        sharpe_ratio = (returns.mean() * 252) / (returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0

        # 计算最大回撤
        cumulative = (1 + returns).cumprod()
        max_peak = cumulative.cummax()
        drawdown = (cumulative - max_peak) / max_peak
        max_drawdown = drawdown.min() * 100

        performance.append({
            'name': info['name'],
            'color': info['color'],
            'total_return': round(total_return, 2),
            'annual_return': round(annual_return, 2),
            'annual_volatility': round(annual_volatility, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'max_drawdown': round(max_drawdown, 2)
        })

    return performance


def calculate_performance_metrics(portfolio_values, dates):
    """计算投资组合的绩效指标"""
    # 计算每日收益率
    daily_returns = portfolio_values.pct_change().dropna()
    
    # 计算年化波动率
    annual_volatility = daily_returns.std() * (252 ** 0.5) * 100
    
    # 使用时间加权收益率计算年化收益（适用于定投策略）
    # 时间加权收益率 = (1+r1)*(1+r2)*...*(1+rn)^(252/n) - 1
    if len(daily_returns) > 0:
        cumulative_return = (1 + daily_returns).prod()
        days = (dates.iloc[-1] - dates.iloc[0]).days
        annual_return = (cumulative_return ** (365.25 / days) - 1) * 100
    else:
        annual_return = 0
    
    # 计算夏普比率（假设无风险利率为2%）
    risk_free_rate = 0.02
    sharpe_ratio = (annual_return / 100 - risk_free_rate) / (annual_volatility / 100) if annual_volatility > 0 else 0
    
    # 计算最大回撤
    cumulative = (1 + daily_returns).cumprod()
    max_peak = cumulative.cummax()
    drawdown = (cumulative - max_peak) / max_peak
    max_drawdown = drawdown.min() * 100 if len(drawdown) > 0 else 0
    
    return {
        'annual_return': round(annual_return, 2),
        'annual_volatility': round(annual_volatility, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'max_drawdown': round(max_drawdown, 2)
    }


def calculate_metrics_from_returns(daily_returns, dates):
    """从每日收益率计算绩效指标"""
    if len(daily_returns) == 0:
        return {
            'annual_return': 0,
            'annual_volatility': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0
        }
    
    # 计算年化波动率
    annual_volatility = daily_returns.std() * (252 ** 0.5) * 100
    
    # 使用时间加权收益率计算年化收益
    cumulative_return = (1 + daily_returns).prod()
    days = (dates.iloc[-1] - dates.iloc[0]).days
    annual_return = (cumulative_return ** (365.25 / days) - 1) * 100
    
    # 计算夏普比率（假设无风险利率为2%）
    risk_free_rate = 0.02
    sharpe_ratio = (annual_return / 100 - risk_free_rate) / (annual_volatility / 100) if annual_volatility > 0 else 0
    
    # 计算最大回撤
    cumulative = (1 + daily_returns).cumprod()
    max_peak = cumulative.cummax()
    drawdown = (cumulative - max_peak) / max_peak
    max_drawdown = drawdown.min() * 100
    
    return {
        'annual_return': round(annual_return, 2),
        'annual_volatility': round(annual_volatility, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'max_drawdown': round(max_drawdown, 2)
    }


def get_portfolio_performance():
    """获取定投策略表现数据"""
    data = load_index_data()

    if not data:
        return None

    # 对齐日期范围
    start_dates = []
    end_dates = []

    for code, info in data.items():
        df = info['df']
        start_dates.append(df['date'].min())
        end_dates.append(df['date'].max())

    common_start = max(start_dates)
    common_end = min(end_dates)

    # 存储标准化后的数据
    normalized_data = {}
    for code, info in data.items():
        df = info['df'].copy()
        df = df[(df['date'] >= common_start) & (df['date'] <= common_end)]
        df = df.sort_values('date').reset_index(drop=True)
        first_close = df['close'].iloc[0]
        df['normalized_close'] = df['close'] / first_close * 100
        normalized_data[code] = df

    # 权重配置
    weights = {
        "NDX": 0.4,
        "000922": 0.4,
        "AU9999": 0.2
    }

    # 合并数据
    combined_df = None
    for code, df in normalized_data.items():
        if combined_df is None:
            combined_df = df[['date', 'normalized_close']].rename(columns={'normalized_close': code})
        else:
            combined_df = combined_df.merge(df[['date', 'normalized_close']], on='date', how='inner').rename(columns={'normalized_close': code})

    combined_df = combined_df.sort_values('date').reset_index(drop=True)
    dates = combined_df['date']

    # 策略1：定投（无再平衡）
    portfolio_cumulative_no_rebal, _, _, total_invested_no_rebal, daily_returns_no_rebal = backtest_dca_with_rebalancing(
        combined_df, weights, threshold=1.0
    )
    no_rebal_total = portfolio_cumulative_no_rebal.iloc[-1]
    no_rebal_profit = no_rebal_total - total_invested_no_rebal
    no_rebal_profit_pct = (no_rebal_profit / total_invested_no_rebal) * 100
    
    # 计算策略1的绩效指标（使用排除定投影响的真实收益率）
    metrics_no_rebal = calculate_metrics_from_returns(daily_returns_no_rebal, dates)
    
    # 策略2：定投（带再平衡）
    portfolio_cumulative_rebal, _, _, total_invested_rebal, daily_returns_rebal = backtest_dca_with_rebalancing(
        combined_df, weights, threshold=0.05
    )
    rebal_total = portfolio_cumulative_rebal.iloc[-1]
    rebal_profit = rebal_total - total_invested_rebal
    rebal_profit_pct = (rebal_profit / total_invested_rebal) * 100
    
    # 计算策略2的绩效指标（使用排除定投影响的真实收益率）
    metrics_rebal = calculate_metrics_from_returns(daily_returns_rebal, dates)

    return [
        {
            'name': '定投组合 (无再平衡)',
            'color': '#FF4444',
            'total_return': round(no_rebal_profit_pct, 2),
            'total_invested': round(total_invested_no_rebal, 0),
            'final_value': round(no_rebal_total, 2),
            'profit': round(no_rebal_profit, 2),
            'annual_return': metrics_no_rebal['annual_return'],
            'annual_volatility': metrics_no_rebal['annual_volatility'],
            'sharpe_ratio': metrics_no_rebal['sharpe_ratio'],
            'max_drawdown': metrics_no_rebal['max_drawdown']
        },
        {
            'name': '定投组合 (5%偏差再平衡)',
            'color': '#FF8C00',
            'total_return': round(rebal_profit_pct, 2),
            'total_invested': round(total_invested_rebal, 0),
            'final_value': round(rebal_total, 2),
            'profit': round(rebal_profit, 2),
            'annual_return': metrics_rebal['annual_return'],
            'annual_volatility': metrics_rebal['annual_volatility'],
            'sharpe_ratio': metrics_rebal['sharpe_ratio'],
            'max_drawdown': metrics_rebal['max_drawdown']
        }
    ]


if __name__ == "__main__":
    # 测试
    fig = render_index_comparison_chart()
    if fig:
        fig.show()
    
    performance = get_index_performance()
    if performance:
        print("\n指数表现:")
        for p in performance:
            print(f"{p['name']}: 总收益={p['total_return']}%, 波动率={p['annual_volatility']}%, 夏普={p['sharpe_ratio']}, 回撤={p['max_drawdown']}%")
    
    portfolio_perf = get_portfolio_performance()
    if portfolio_perf:
        print("\n定投策略表现:")
        for p in portfolio_perf:
            print(f"{p['name']}: 累计投入=¥{p['total_invested']:,.0f}, 期末总值=¥{p['final_value']:,.2f}, 收益=¥{p['profit']:,.2f} ({p['total_return']}%)")