import json
import os
from datetime import date, datetime

HISTORY_PATH = "net_value_history.json"

def load_net_value_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_net_value_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_today_str():
    return date.today().strftime("%Y-%m-%d")

def get_net_value_from_history(fund_code):
    history = load_net_value_history()
    today = get_today_str()
    
    if fund_code in history:
        fund_history = history[fund_code]
        if today in fund_history:
            return fund_history[today]
    return None

def save_net_value_to_history(fund_code, net_value_data):
    history = load_net_value_history()
    
    if fund_code not in history:
        history[fund_code] = {}
    
    today = get_today_str()
    history[fund_code][today] = {
        "date": net_value_data["date"].strftime("%Y-%m-%d") if hasattr(net_value_data["date"], "strftime") else str(net_value_data["date"]),
        "net_value": net_value_data["net_value"],
        "change": net_value_data["change"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    save_net_value_history(history)

def get_fund_history_data(fund_code):
    history = load_net_value_history()
    return history.get(fund_code, {})