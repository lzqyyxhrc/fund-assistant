import os
import json
import requests
from datetime import datetime
from openai import OpenAI

CONFIG_PATH = "funds_config.json"
NET_VALUE_HISTORY_PATH = "net_value_history.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "targets": {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2},
        "funds": {"nasdaq": [], "dividend": [], "gold": []}
    }

def load_net_values():
    if os.path.exists(NET_VALUE_HISTORY_PATH):
        with open(NET_VALUE_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data:
                # 返回最新日期的净值数据，结构是 {基金代码: 最新净值数据}
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

def generate_daily_report(api_key=None):
    """使用 DeepSeek API 生成每日报告"""
    
    # 配置 DeepSeek API
    if not api_key:
        api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        print("错误: 请提供 API key")
        return None
    
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
    new_investment = 1200  # 默认定投金额
    
    rebalancing_amounts = calculate_rebalancing_amounts(targets, category_values, total_value, new_investment)
    
    # 准备请求消息
    messages = [
        {
            "role": "system",
            "content": "你是一位专业的基金投资顾问，擅长分析投资组合和生成专业的投资报告。请用中文回复。"
        },
        {
            "role": "user",
            "content": f"""
请帮我生成一份{today}的基金投资日报，包含以下内容：

【实际持仓数据】
- 总资产市值: ¥{total_value:,.2f}
- 纳指类资产当前占比: {current_weights['nasdaq']}%，目标40%，当前市值¥{category_values.get('nasdaq', 0):,.2f}
- 红利低波类资产当前占比: {current_weights['dividend']}%，目标40%，当前市值¥{category_values.get('dividend', 0):,.2f}
- 黄金类资产当前占比: {current_weights['gold']}%，目标20%，当前市值¥{category_values.get('gold', 0):,.2f}

【定投分配方案（基于再平衡算法）】
假设今日定投¥{new_investment}，建议分配如下：
- 纳指类: ¥{rebalancing_amounts.get('nasdaq', 0):,.2f}
- 红利低波类: ¥{rebalancing_amounts.get('dividend', 0):,.2f}
- 黄金类: ¥{rebalancing_amounts.get('gold', 0):,.2f}

1. 市场概览
   - 今日全球主要市场表现（美股、A股、港股）
   - 主要指数走势分析

2. 基金投资组合分析
   - 资产配置比例（基于上述实际持仓数据）
   - 各类资产表现分析
   - 仓位偏离度评估

3. 定投建议
   - 基于以上精确的再平衡分配方案，给出具体的定投建议
   - 在报告中直接使用这些数字，格式如："建议今日投入¥{new_investment}，其中纳指¥{rebalancing_amounts.get('nasdaq', 0):,.2f}、红利¥{rebalancing_amounts.get('dividend', 0):,.2f}、黄金¥{rebalancing_amounts.get('gold', 0):,.2f}"
   - 说明是否需要再平衡调整及原因

4. 市场热点与风险提示
   - 今日重要财经新闻
   - 潜在风险因素

请以专业、简洁的格式输出报告。
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

def save_report(report_content):
    """保存报告到文件"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = "reports"
    
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)
    
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
    
    # 飞书消息格式
    payload = {
        "msg_type": "text",
        "content": {
            "text": f"📊 **{today} 基金投资日报**\n\n{report_content}"
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
