import json
import os
from datetime import datetime, timedelta

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

def is_trading_day(check_date=None):
    """判断是否为交易日（简单判断：周一到周五）"""
    if check_date is None:
        check_date = datetime.now()
    if isinstance(check_date, str):
        check_date = datetime.strptime(check_date, "%Y-%m-%d")
    return check_date.weekday() < 5

def get_t_plus_n_date(base_date_str, days=2, after_15h=False):
    """计算基金确认日期（考虑交易日和15:00时间分界）
    
    规则：
    - 15:00前提交申购：按T日计算
    - 15:00后提交申购：视为T+1日申请
    
    Args:
        base_date_str: 基准日期，格式为 "YYYY-MM-DD"
        days: 需要往后数的交易日天数，QDII基金用2（T+2），A股基金用1（T+1）
        after_15h: 是否在15:00后提交，默认为False
    
    Returns:
        str: 确认日期，格式为 "YYYY-MM-DD"
    """
    base_date = datetime.strptime(base_date_str, "%Y-%m-%d")
    
    # 15:00后申购，基准日期往后推1天（视为T+1日申请）
    if after_15h:
        base_date += timedelta(days=1)
    
    days_added = 0
    current_date = base_date
    
    while days_added < days:
        current_date += timedelta(days=1)
        if is_trading_day(current_date):
            days_added += 1
    
    return current_date.strftime("%Y-%m-%d")

def get_fund_confirm_date(base_date_str, fund_category, after_15h=False):
    """根据基金类型获取份额确认日期（份额正式到账日期）
    
    所有基金类型的份额正式到账时间均为T+2日，区别在于：
    - QDII基金：T+1日晚间确认份额
    - A股指数基金/黄金ETF联接：T+1日白天确认份额
    
    Args:
        base_date_str: 基准日期，格式为 "YYYY-MM-DD"
        fund_category: 基金类型，如 'nasdaq', 'dividend', 'gold'
        after_15h: 是否在15:00后提交，默认为False
    
    Returns:
        str: 份额正式到账日期，格式为 "YYYY-MM-DD"
    """
    # 所有基金类型均使用T+2确认（份额正式到账日期）
    # 15:00后提交视为T+1日申请，需额外加1天
    return get_t_plus_n_date(base_date_str, days=2, after_15h=after_15h)

def confirm_pending_shares(funds_config, net_values=None):
    """检查并确认到期的待确认份额
    
    在确认日，根据当日净值计算实际份额：待确认份额 = 待确认金额 / 确认日净值
    
    Args:
        funds_config: 基金配置
        net_values: 净值数据（用于确认日计算份额）
        
    Returns:
        int: 确认的份额数量
    """
    today = datetime.now().strftime("%Y-%m-%d")
    confirmed_count = 0
    
    for category in funds_config["funds"]:
        for fund in funds_config["funds"][category]:
            pending_date = fund.get("pending_confirm_date")
            if pending_date and pending_date <= today:
                # 待确认金额
                pending_amount = fund.get("pending_amount", 0.0)
                
                if pending_amount > 0:
                    # 根据确认日净值计算实际份额
                    confirm_day_net_value = fund.get("cost_price", 1.0)  # 默认使用成本价作为保底
                    
                    if net_values and fund["code"] in net_values:
                        confirm_day_net_value = net_values[fund["code"]]["net_value"]
                    
                    # 实际确认份额 = 待确认金额 / 确认日净值
                    actual_shares = pending_amount / confirm_day_net_value
                    
                    shares = fund.get("shares", 0.0)
                    cost_price = fund.get("cost_price", 0.0)
                    
                    if shares > 0:
                        # 摊薄成本价
                        new_cost_price = (shares * cost_price + actual_shares * confirm_day_net_value) / (shares + actual_shares)
                        fund["cost_price"] = round(new_cost_price, 4)
                    else:
                        fund["cost_price"] = confirm_day_net_value
                    
                    fund["shares"] = round(shares + actual_shares, 4)
                    fund["pending_amount"] = 0.0
                    fund["pending_confirm_date"] = None
                    confirmed_count += 1
                else:
                    # 金额为0，直接清空
                    fund["pending_amount"] = 0.0
                    fund["pending_confirm_date"] = None
    
    return confirmed_count

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
    
    新增QDII T+2确认逻辑：新申购份额先放入待确认状态，T+2个交易日后自动确认。
    
    Args:
        funds_config: 基金配置
        net_values: 净值数据
        auto_invest_funds: 定投计划列表
        force: 是否强制执行（跳过幂等性检查），默认为False
    
    Returns:
        tuple: (transactions, total_amount)
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    
    # 幂等性检查：除非强制，否则检查当天是否已有定投记录
    if not force and has_invested_today(today):
        print(f"幂等性检查：{today} 已有定投记录，跳过执行")
        return None, 0
    
    # 判断是否在15:00后提交（15:00后视为T+1日申请）
    after_15h = now.hour >= 15
    if after_15h:
        print(f"当前时间 {now.strftime('%H:%M')} 已过15:00，视为T+1日申请")
    
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
            
            # 根据基金类型计算确认日期
            confirm_date = get_fund_confirm_date(today, category, after_15h=after_15h)
            
            if category:
                funds_list = funds_config["funds"].get(category, [])
                found = False
                for fund in funds_list:
                    if fund["code"] == code:
                        # 将新申购金额放入待确认状态（记录金额而非份额）
                        pending_amount = fund.get("pending_amount", 0.0)
                        fund["pending_amount"] = round(pending_amount + amount, 2)
                        fund["pending_confirm_date"] = confirm_date
                        found = True
                        break
                if not found:
                    funds_config["funds"][category].append({
                        "code": code,
                        "name": fund_name,
                        "shares": 0.0,
                        "cost_price": net_value,
                        "pending_amount": round(amount, 2),
                        "pending_confirm_date": confirm_date
                    })
            
            total_amount += amount
            
            transactions.append({
                "date": today,
                "confirm_date": confirm_date,
                "category": category or "other",
                "code": code,
                "name": fund_name,
                "amount": round(amount, 2),
                "shares": round(shares_to_buy, 4),
                "net_value": net_value,
                "status": "pending"
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