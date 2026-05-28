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

def should_auto_invest_now(auto_config):
    if not auto_config.get("enabled", False):
        return False
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    last_date = auto_config.get("last_invest_date")
    
    if last_date == today_str:
        return False
    
    if not is_trading_day():
        return False
    
    return True

def execute_auto_invest(funds_config, net_values, auto_invest_funds):
    today = datetime.now().strftime("%Y-%m-%d")
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
                        fund["shares"] = round(fund["shares"] + shares_to_buy, 4)
                        found = True
                        break
                if not found:
                    funds_config["funds"][category].append({
                        "code": code,
                        "name": fund_name,
                        "shares": round(shares_to_buy, 4)
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