import json
import os
from datetime import datetime, time

AUTO_INVEST_CONFIG_PATH = "auto_invest_config.json"
INVEST_HISTORY_PATH = "invest_history.json"

def load_auto_invest_config():
    if os.path.exists(AUTO_INVEST_CONFIG_PATH):
        with open(AUTO_INVEST_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "enabled": False,
        "last_invest_date": None,
        "auto_invest_funds": []
    }

def save_auto_invest_config(config):
    with open(AUTO_INVEST_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_invest_history():
    if os.path.exists(INVEST_HISTORY_PATH):
        with open(INVEST_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_invest_history(history):
    with open(INVEST_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def is_trading_day():
    today = datetime.now()
    return today.weekday() < 5

def has_invested_today(check_date=None):
    """检查指定日期是否已有定投记录（幂等性校验）
    
    Args:
        check_date: 要检查的日期，默认为今天
    Returns:
        bool: 如果当天已有定投记录返回True，否则返回False
    """
    if check_date is None:
        check_date = datetime.now().strftime("%Y-%m-%d")
    
    history = load_invest_history()
    for record in history:
        if record.get("date") == check_date:
            return True
    return False

def should_auto_invest_now(auto_config):
    """判断是否应该执行自动定投（包含幂等性检查）"""
    if not auto_config.get("enabled", False):
        return False
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    # 幂等性检查：检查历史记录中是否已有当天记录
    if has_invested_today(today_str):
        return False
    
    # 额外检查配置文件中的日期（冗余检查，增加安全性）
    last_date = auto_config.get("last_invest_date")
    if last_date == today_str:
        return False
    
    if not is_trading_day():
        return False
    
    return True

def execute_auto_invest(funds_config, net_values, auto_invest_funds, force=False):
    """执行定投操作（支持幂等性）
    
    Args:
        funds_config: 基金配置
        net_values: 净值数据
        auto_invest_funds: 定投计划列表
        force: 是否强制执行（跳过幂等性检查），默认为False
    
    Returns:
        tuple: (transactions, total_amount)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 幂等性检查：除非强制，否则检查当天是否已有定投记录
    if not force and has_invested_today(today):
        print(f"幂等性检查：{today} 已有定投记录，跳过执行")
        return None, 0
    
    total_amount = 0
    transactions = []
    
    for fund_plan in auto_invest_funds:
        code = fund_plan["code"].strip()
        amount = fund_plan["amount"]
        
        if amount > 0 and code and code in net_values:
            net_value = net_values[code]["net_value"]
            shares_to_buy = amount / net_value
            
            fund_name = net_values[code].get("name", code)
            
            category = find_fund_category(funds_config, code)
            
            if category:
                funds_list = funds_config["funds"].get(category, [])
                found = False
                for fund in funds_list:
                    if fund["code"] == code:
                        # 计算加权平均成本价
                        old_shares = fund["shares"]
                        old_cost_price = fund.get("cost_price", 0.0)
                        new_shares = old_shares + shares_to_buy
                        
                        if old_shares > 0:
                            # 摊薄成本价 = (原有份额 × 原有成本价 + 新增份额 × 当前净值) / 总份额
                            new_cost_price = (old_shares * old_cost_price + shares_to_buy * net_value) / new_shares
                        else:
                            new_cost_price = net_value
                        
                        fund["shares"] = round(new_shares, 4)
                        fund["cost_price"] = round(new_cost_price, 4)
                        found = True
                        break
                if not found:
                    funds_config["funds"][category].append({
                        "code": code,
                        "name": fund_name,
                        "shares": round(shares_to_buy, 4),
                        "cost_price": round(net_value, 4)
                    })
            
            total_amount += amount
            
            transactions.append({
                "date": today,
                "category": category or "other",
                "code": code,
                "name": fund_name,
                "amount": round(amount, 2),
                "shares": round(shares_to_buy, 4),
                "net_value": net_value
            })
    
    if transactions:
        history = load_invest_history()
        
        # 再次幂等性检查：写入前最后验证
        for record in history:
            if record.get("date") == today:
                print(f"写入前检查：{today} 已存在记录，跳过写入")
                return None, 0
        
        history.append({
            "date": today,
            "total_amount": total_amount,
            "transactions": transactions
        })
        save_invest_history(history)
        
        auto_config = load_auto_invest_config()
        auto_config["last_invest_date"] = today
        save_auto_invest_config(auto_config)
    
    return transactions, total_amount

def check_and_execute_auto_invest(funds_config, net_values):
    auto_config = load_auto_invest_config()
    
    if should_auto_invest_now(auto_config):
        auto_invest_funds = auto_config.get("auto_invest_funds", [])
        return execute_auto_invest(funds_config, net_values, auto_invest_funds)
    
    return None, 0

def find_fund_category(funds_config, code):
    for category, funds in funds_config["funds"].items():
        for fund in funds:
            if fund["code"] == code:
                return category
    return None