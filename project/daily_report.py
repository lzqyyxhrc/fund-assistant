import os
import json
import requests
from datetime import datetime
from openai import OpenAI
from services.storage import load_config as load_config_from_db
from services.net_value_storage import load_net_value_history


def load_config():
    return load_config_from_db()


def load_net_values():
    data = load_net_value_history()
    if data:
        result = {}
        for code, dates in data.items():
            if dates:
                latest_date = max(dates.keys())
                result[code] = dates[latest_date]
        return result
    return {}

def calculate_category_value(config, net_values):
    """计算各类资产市值"""
    category_values = {}
    for category, funds in config["funds"].items():
        total_value = 0
        for fund in funds:
            if fund["code"] in net_values:
                total_value += fund["shares"] * net_values[fund["code"]]["net_value"]
        category_values[category] = total_value
    return category_values

def calculate_current_weights(config, net_values):
    category_values = calculate_category_value(config, net_values)
    total = sum(category_values.values())
    if total == 0:
        return {"nasdaq": 0, "dividend": 0, "gold": 0}
    
    return {k: round(v / total * 100, 1) for k, v in category_values.items()}

def calculate_rebalancing_amounts(targets, category_values, total_value, new_investment, threshold=0.02):
    """计算再平衡定投金额分配"""
    if total_value == 0:
        return {category: round(new_investment * targets[category], 2) for category in targets.keys()}
    
    current_weights = {k: v / total_value for k, v in category_values.items()}
    deviations = {k: current_weights.get(k, 0) - targets[k] for k in targets.keys()}
    
    need_rebalance = any(abs(d) > threshold for d in deviations.values())
    
    if not need_rebalance:
        return {category: round(new_investment * targets[category], 2) for category in targets.keys()}
    
    total_with_new = total_value + new_investment
    underweight = {}
    overweight = {}
    
    for category, target_weight in targets.items():
        current_value = category_values.get(category, 0)
        target_value = total_with_new * target_weight
        amount_needed = target_value - current_value
        
        if amount_needed > 0:
            underweight[category] = {"needed": amount_needed, "deviation": deviations[category]}
        else:
            overweight[category] = {"needed": abs(amount_needed), "deviation": deviations[category]}
    
    total_underweight = sum(c["needed"] for c in underweight.values())
    
    if total_underweight > 0:
        amounts = {category: 0.0 for category in targets.keys()}
        for category, info in underweight.items():
            priority = abs(info["deviation"])
            base_amount = (info["needed"] / total_underweight) * new_investment
            amounts[category] = round(base_amount * (1 + priority * 2), 2)
        
        total_allocated = sum(amounts.values())
        if total_allocated > 0:
            scale = new_investment / total_allocated
            amounts = {k: round(v * scale, 2) for k, v in amounts.items()}
        
        return amounts
    else:
        return {category: round(new_investment / len(targets), 2) for category in targets.keys()}

def generate_simple_report():
    """生成简单的每日报告（无需API key）"""
    config = load_config()
    net_values = load_net_values()
    
    category_values = calculate_category_value(config, net_values)
    current_weights = calculate_current_weights(config, net_values)
    total_value = sum(category_values.values())
    
    # 计算待确认金额（支持多笔待确认订单）
    pending_total = 0
    for category, funds in config["funds"].items():
        for fund in funds:
            pending_orders = fund.get("pending_orders", [])
            pending_total += sum(order.get("amount", 0) for order in pending_orders)
    
    targets = config.get("targets", {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2})
    
    report = f"""基金投资日报
====================================

日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

【总资产概览】
----------------
总市值: {total_value:,.2f}
待确认金额: {pending_total:,.2f}

【资产配置】
----------------
| 资产类别 | 市值 | 当前占比 | 目标占比 | 偏离度 |
|---------|------|---------|---------|--------|
| 纳斯达克 | {category_values.get('nasdaq', 0):,.2f} | {current_weights.get('nasdaq', 0):.1f}% | {targets['nasdaq'] * 100:.0f}% | {current_weights.get('nasdaq', 0) - targets['nasdaq'] * 100:+.1f}% |
| 红利低波 | {category_values.get('dividend', 0):,.2f} | {current_weights.get('dividend', 0):.1f}% | {targets['dividend'] * 100:.0f}% | {current_weights.get('dividend', 0) - targets['dividend'] * 100:+.1f}% |
| 黄金ETF | {category_values.get('gold', 0):,.2f} | {current_weights.get('gold', 0):.1f}% | {targets['gold'] * 100:.0f}% | {current_weights.get('gold', 0) - targets['gold'] * 100:+.1f}% |

【持仓明细】
----------------
"""
    
    category_names = {
        "nasdaq": "纳斯达克",
        "dividend": "红利低波",
        "gold": "黄金ETF"
    }
    
    for category, funds in config["funds"].items():
        report += f"\n【{category_names.get(category, category)}】\n"
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                market_value = fund["shares"] * nv["net_value"]
                cost_value = fund["shares"] * fund.get("cost_price", 0)
                profit = market_value - cost_value
                profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0
                change = nv.get("change", 0)
                
                name = fund['name']
                # 解码Unicode转义字符（处理中文乱码）
                try:
                    # 处理已编码的Unicode转义字符
                    if isinstance(name, str):
                        # 尝试从原始字符串解码
                        name = name.encode('latin-1').decode('unicode-escape')
                except:
                    try:
                        # 其他解码方式
                        if isinstance(name, str) and '\\u' in repr(name):
                            name = bytes(name, 'utf-8').decode('unicode_escape')
                    except:
                        pass
                
                # 计算待确认金额（支持多笔待确认订单）
                pending_orders = fund.get("pending_orders", [])
                pending = sum(order.get("amount", 0) for order in pending_orders)
                pending_str = f" (待确认: {pending:.2f})" if pending > 0 else ""
                
                report += f"  {name} ({fund['code']}): {fund['shares']:.4f}份 @ {nv['net_value']:.4f} = {market_value:,.2f} | 成本: {cost_value:,.2f} | 收益: {profit:+.2f} ({profit_pct:+.2f}%) | 日涨跌: {change:+.2f}%{pending_str}\n"
    
    report += f"\n====================================\n报告结束"
    return report

def generate_daily_report(api_key=None):
    """生成每日报告（优先使用API，无API时生成简单报告）"""
    
    # 如果没有API key，生成简单报告
    if not api_key:
        api_key = os.environ.get('DEEPSEEK_API_KEY')
    
    if not api_key:
        print("未配置API key，生成简单报告")
        return generate_simple_report()
    
    # 配置 DeepSeek API
    print("使用DeepSeek API生成报告...")
    
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )
    
    # 获取当前日期
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 加载配置和净值数据，计算实际仓位
    config = load_config()
    net_values = load_net_values()
    current_weights = calculate_current_weights(config, net_values)
    
    # 计算再平衡定投金额
    category_values = calculate_category_value(config, net_values)
    total_value = sum(category_values.values())
    targets = config.get("targets", {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2})
    
    # 计算待确认金额（支持多笔待确认订单）
    pending_total = 0
    for category, funds in config["funds"].items():
        for fund in funds:
            pending_orders = fund.get("pending_orders", [])
            pending_total += sum(order.get("amount", 0) for order in pending_orders)
    
    # 计算各类资产收益
    category_profit = {}
    category_cost = {}
    for category in ["nasdaq", "dividend", "gold"]:
        cost = 0
        market = 0
        for fund in config["funds"].get(category, []):
            if fund["code"] in net_values:
                cost += fund["shares"] * fund.get("cost_price", 0)
                market += fund["shares"] * net_values[fund["code"]]["net_value"]
        category_cost[category] = cost
        category_profit[category] = market - cost
    
    # 准备持仓明细
    holdings_detail = []
    for category, funds in config["funds"].items():
        for fund in funds:
            if fund["code"] in net_values:
                nv = net_values[fund["code"]]
                market_value = fund["shares"] * nv["net_value"]
                cost_value = fund["shares"] * fund.get("cost_price", 0)
                profit = market_value - cost_value
                profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0
                holdings_detail.append({
                    "name": fund["name"],
                    "code": fund["code"],
                    "category": category,
                    "shares": fund["shares"],
                    "net_value": nv["net_value"],
                    "cost_price": fund.get("cost_price", 0),
                    "market_value": market_value,
                    "profit": profit,
                    "profit_pct": profit_pct,
                    "change": nv.get("change", 0),
                    "pending_amount": sum(order.get("amount", 0) for order in fund.get("pending_orders", []))
                })
    
    # 准备请求消息
    messages = [
        {
            "role": "system",
            "content": """你是一位专业的基金投资顾问，擅长分析投资组合和生成专业的投资报告。
请用中文回复，格式清晰，使用markdown格式。
报告应该包含：日期、总资产概览、资产配置表、持仓明细、市场分析、定投建议等部分。"""
        },
        {
            "role": "user",
            "content": f"""
请帮我生成一份{today}的基金投资日报，基于以下实际持仓数据：

【基本信息】
- 报告日期: {today}
- 总资产市值: {total_value:,.2f}
- 待确认金额: {pending_total:,.2f}

【资产配置】
| 资产类别 | 市值 | 当前占比 | 目标占比 | 偏离度 | 收益 |
|---------|------|---------|---------|--------|------|
| 纳斯达克 | {category_values.get('nasdaq', 0):,.2f} | {current_weights.get('nasdaq', 0):.1f}% | {targets['nasdaq'] * 100:.0f}% | {current_weights.get('nasdaq', 0) - targets['nasdaq'] * 100:+.1f}% | {category_profit.get('nasdaq', 0):+.2f} |
| 红利低波 | {category_values.get('dividend', 0):,.2f} | {current_weights.get('dividend', 0):.1f}% | {targets['dividend'] * 100:.0f}% | {current_weights.get('dividend', 0) - targets['dividend'] * 100:+.1f}% | {category_profit.get('dividend', 0):+.2f} |
| 黄金ETF | {category_values.get('gold', 0):,.2f} | {current_weights.get('gold', 0):.1f}% | {targets['gold'] * 100:.0f}% | {current_weights.get('gold', 0) - targets['gold'] * 100:+.1f}% | {category_profit.get('gold', 0):+.2f} |

【持仓明细】
{json.dumps(holdings_detail, ensure_ascii=False, indent=2)}

请生成一份专业的投资日报，包含：
1. 市场概览 - 简要分析今日全球主要市场表现
2. 投资组合分析 - 基于上述数据进行资产配置分析
3. 持仓明细 - 展示各基金的持仓情况、收益等
4. 定投建议 - 根据当前仓位偏离情况给出定投建议
5. 风险提示 - 简要提示潜在风险因素

请使用中文，格式清晰易读。
"""
        }
    ]
    
    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}}
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"调用 DeepSeek API 失败: {e}")
        return None

def decode_unicode_text(text):
    """解码Unicode转义字符，处理中文乱码"""
    if not text:
        return text
    
    # 检查是否包含Unicode转义序列
    if '\\u' in text:
        try:
            # 处理已编码的Unicode转义字符
            return text.encode('latin-1').decode('unicode-escape')
        except:
            try:
                return bytes(text, 'utf-8').decode('unicode_escape')
            except:
                pass
    
    return text

def save_report(report_content):
    """保存报告到文件"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = "reports"
    
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)
    
    # 解码可能的Unicode转义字符
    report_content = decode_unicode_text(report_content)
    
    filename = f"{report_dir}/daily_report_{today}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 基金投资日报\n\n")
        f.write(f"**生成日期**: {today}\n\n")
        f.write(f"---\n\n")
        f.write(report_content)
    
    print(f"报告已保存: {filename}")
    return filename

def send_to_feishu(report_content, webhook_url):
    """发送报告到飞书"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 解码可能的Unicode转义字符
    report_content = decode_unicode_text(report_content)
    
    # 飞书消息格式
    payload = {
        "msg_type": "text",
        "content": {
            "text": f"【{today} 基金投资日报】\n\n{report_content}"
        }
    }
    
    try:
        response = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                print("报告已发送到飞书")
                return True
            else:
                print(f"飞书发送失败: {result.get('msg', '未知错误')}")
        else:
            print(f"飞书发送失败，HTTP状态码: {response.status_code}")
    except Exception as e:
        print(f"发送到飞书失败: {e}")
    
    return False

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="每日报告生成器")
    parser.add_argument("--api-key", "-k", help="DeepSeek API Key")
    parser.add_argument("--feishu-webhook", "-f", help="飞书机器人 Webhook 地址")
    args = parser.parse_args()
    
    print("=== 每日报告生成器 ===")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    report = generate_daily_report(api_key=args.api_key)
    
    if report:
        print("\n=== 生成的报告 ===")
        print(report)
        print("\n" + "="*50)
        save_report(report)
        
        if args.feishu_webhook:
            send_to_feishu(report, args.feishu_webhook)
    else:
        print("报告生成失败")

if __name__ == "__main__":
    main()
