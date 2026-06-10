"""
指数数据回测脚本
使用下载的指数数据进行回测分析
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

def load_all_index_data(data_dir="data/index"):
    """加载所有可用的指数数据"""
    indices = {
        "NDX": "纳斯达克100",
        "512890": "红利低波ETF",
        "AU9999": "黄金"
    }

    data = {}
    for code, name in indices.items():
        df = load_index_data(code, data_dir)
        if df is not None:
            data[code] = {
                "name": name,
                "df": df
            }
            print(f"[OK] Loaded {name} data: {len(df)} records")

    return data


def load_index_data(index_code, data_dir="data/index"):
    """加载单个指数数据，优先加载全收益指数"""
    if not os.path.exists(data_dir):
        return None

    files = [f for f in os.listdir(data_dir) if f.startswith(index_code) and f.endswith('.csv')]

    if not files:
        return None

    # 优先选择全收益指数数据
    total_return_files = [f for f in files if 'total_return' in f or '全收益' in f]
    if total_return_files:
        latest_file = sorted(total_return_files)[-1]
        print(f"[INFO] 使用全收益指数数据: {latest_file}")
    else:
        latest_file = sorted(files)[-1]
        print(f"[INFO] 使用价格指数数据: {latest_file}")

    filepath = os.path.join(data_dir, latest_file)

    df = pd.read_csv(filepath, encoding='utf-8-sig')

    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])

    return df


def calculate_returns(df, period='daily'):
    """计算收益率"""
    if 'close' not in df.columns:
        return None

    df = df.copy()
    df['return'] = df['close'].pct_change()

    if period == 'monthly':
        df['return'] = df['close'].pct_change(21)  # 近似月度收益
    elif period == 'yearly':
        df['return'] = df['close'].pct_change(252)  # 近似年度收益

    return df


def calculate_metrics(df):
    """计算各种风险收益指标"""
    if 'return' not in df.columns:
        df = calculate_returns(df)

    returns = df['return'].dropna()

    # 使用复利方法计算年化收益
    if len(returns) > 0:
        cumulative_return = (1 + returns).prod()
        annual_return = (cumulative_return ** (252 / len(returns)) - 1) * 100
    else:
        annual_return = 0
    
    metrics = {
        'total_return': (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100,
        'annual_return': annual_return,
        'annual_volatility': returns.std() * np.sqrt(252) * 100,
        'sharpe_ratio': (annual_return / 100 - 0.02) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0,
        'max_drawdown': calculate_max_drawdown(df['close']) * 100,
        'win_rate': (returns > 0).sum() / len(returns) * 100,
        'best_day': returns.max() * 100,
        'worst_day': returns.min() * 100,
    }

    return metrics


def calculate_max_drawdown(prices):
    """计算最大回撤"""
    cummax = prices.cummax()
    drawdown = (prices - cummax) / cummax
    return drawdown.min()


def backtest_rebalance(data, weights, rebalance_freq='monthly'):
    """
    回测再平衡策略

    Args:
        data: dict, 各个指数的DataFrame
        weights: dict, 各指数权重，如 {"NDX": 0.4, "000015": 0.4, "AU9999": 0.2}
        rebalance_freq: str, 再平衡频率 ('daily', 'monthly', 'quarterly')
    """
    # 对齐数据日期
    start_dates = []
    end_dates = []

    for code, info in data.items():
        df = info['df']
        start_dates.append(df['date'].min())
        end_dates.append(df['date'].max())

    common_start = max(start_dates)
    common_end = min(end_dates)

    # 筛选共同日期范围
    filtered_data = {}
    for code, info in data.items():
        df = info['df'].copy()
        df = df[(df['date'] >= common_start) & (df['date'] <= common_end)]
        df = df.sort_values('date').reset_index(drop=True)
        filtered_data[code] = df

    # 合并数据
    combined_df = None
    for code, df in filtered_data.items():
        if combined_df is None:
            combined_df = df[['date', 'close']].rename(columns={'close': code})
        else:
            combined_df = combined_df.merge(df[['date', 'close']].rename(columns={'close': code}),
                                           on='date', how='outer')

    combined_df = combined_df.sort_values('date').reset_index(drop=True)

    # 计算每日收益率
    returns_df = combined_df.drop('date', axis=1).pct_change()

    # 按照权重计算投资组合收益
    portfolio_returns = pd.Series(0.0, index=returns_df.index)
    for code, weight in weights.items():
        if code in returns_df.columns:
            portfolio_returns += returns_df[code] * weight

    portfolio_returns = portfolio_returns.dropna()

    # 计算累计收益
    cumulative_returns = (1 + portfolio_returns).cumprod() - 1

    # 计算各项指标
    metrics = {
        'total_return': cumulative_returns.iloc[-1] * 100,
        'annual_return': portfolio_returns.mean() * 252 * 100,
        'annual_volatility': portfolio_returns.std() * np.sqrt(252) * 100,
        'sharpe_ratio': (portfolio_returns.mean() * 252) / (portfolio_returns.std() * np.sqrt(252)) if portfolio_returns.std() > 0 else 0,
        'max_drawdown': calculate_max_drawdown(cumulative_returns + 1) * 100,
        'start_date': common_start.strftime('%Y-%m-%d'),
        'end_date': common_end.strftime('%Y-%m-%d'),
        'days': len(portfolio_returns)
    }

    return metrics, cumulative_returns


def print_metrics(metrics, title="Metrics"):
    """打印指标"""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    print(f"Period: {metrics.get('start_date', 'N/A')} to {metrics.get('end_date', 'N/A')}")
    print(f"Duration: {metrics.get('days', 0)} trading days")
    print("-" * 60)
    print(f"Total Return: {metrics['total_return']:.2f}%")
    print(f"Annual Return: {metrics['annual_return']:.2f}%")
    print(f"Annual Volatility: {metrics['annual_volatility']:.2f}%")
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
    print("=" * 60)


def main():
    """主函数"""
    print("=" * 60)
    print("Index Data Backtest")
    print("=" * 60)

    # 加载数据
    data = load_all_index_data()

    if not data:
        print("\n[ERROR] No data available for backtesting")
        print("Please run download_index_data.py first")
        return

    # 分别计算各指数指标
    print("\n" + "=" * 60)
    print("Individual Index Performance")
    print("=" * 60)

    for code, info in data.items():
        print(f"\n{info['name']} ({code}):")
        df = calculate_returns(info['df'])
        metrics = calculate_metrics(df)
        print(f"  Total Return: {metrics['total_return']:.2f}%")
        print(f"  Annual Return: {metrics['annual_return']:.2f}%")
        print(f"  Annual Volatility: {metrics['annual_volatility']:.2f}%")
        print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")

    # 回测投资组合策略
    print("\n" + "=" * 60)
    print("Portfolio Backtest (Rebalancing)")
    print("=" * 60)

    # 预设的权重配置（与基金配置一致）
    portfolio_weights = {
        "NDX": 0.4,      # 纳斯达克100 - 40%
        "512890": 0.4,   # 红利低波ETF - 40%
        "AU9999": 0.2    # 黄金 - 20%
    }

    print("\nPortfolio Allocation:")
    for code, weight in portfolio_weights.items():
        name = data.get(code, {}).get('name', code)
        print(f"  {name}: {weight*100:.0f}%")

    # 执行回测
    metrics, cumulative = backtest_rebalance(data, portfolio_weights)
    print_metrics(metrics, "Portfolio Performance")


if __name__ == "__main__":
    main()
