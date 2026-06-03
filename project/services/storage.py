import json
import os

CONFIG_PATH = "funds_config.json"
INVESTMENT_CONFIG_PATH = "investment_config.json"
THRESHOLD_CONFIG_PATH = "threshold_config.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            # 迁移旧数据格式，添加缺失的待确认字段
            for category in config["funds"]:
                for fund in config["funds"][category]:
                    # 迁移旧字段：pending_shares -> pending_amount
                    if "pending_shares" in fund and "pending_amount" not in fund:
                        pending_cost = fund.get("pending_cost_price", 0.0)
                        fund["pending_amount"] = fund["pending_shares"] * pending_cost
                    if "pending_amount" not in fund:
                        fund["pending_amount"] = 0.0
                    # 删除旧字段
                    if "pending_shares" in fund:
                        del fund["pending_shares"]
                    if "pending_cost_price" in fund:
                        del fund["pending_cost_price"]
                    if "pending_confirm_date" not in fund:
                        fund["pending_confirm_date"] = None
            return config
    return {
        "targets": {
            "nasdaq": 0.4,
            "dividend": 0.4,
            "gold": 0.2
        },
        "funds": {
            "nasdaq": [],
            "dividend": [],
            "gold": []
        }
    }

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_investment_amount():
    if os.path.exists(INVESTMENT_CONFIG_PATH):
        with open(INVESTMENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("amount", 1000)
    return 1000

def save_investment_amount(amount):
    with open(INVESTMENT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"amount": amount}, f, ensure_ascii=False, indent=2)

def load_threshold():
    if os.path.exists(THRESHOLD_CONFIG_PATH):
        with open(THRESHOLD_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("rebalance_threshold", 0.02)
    return 0.02

def save_threshold(threshold):
    with open(THRESHOLD_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"rebalance_threshold": threshold}, f, ensure_ascii=False, indent=2)

def get_category_names():
    return {
        "nasdaq": "纳指类",
        "dividend": "红利低波类",
        "gold": "黄金类"
    }

def get_category_color(category):
    colors = {
        "nasdaq": "#1E90FF",
        "dividend": "#32CD32",
        "gold": "#FFD700"
    }
    return colors.get(category, "#808080")