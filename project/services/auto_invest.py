from datetime import datetime, timedelta
from services.storage import (
    save_config,
    load_auto_invest_config,
    save_auto_invest_config,
    load_invest_history,
    save_invest_history
)

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
    
    根据净值日期(net_value_date)来确认份额：
    - 支持多笔待确认订单（每笔有独立的净值日期）
    - 当 net_value_date 的净值已更新时，即可确认该笔订单的份额
    
    Args:
        funds_config: 基金配置
        net_values: 净值数据（用于获取净值日期对应的净值）
        
    Returns:
        int: 确认的订单数量
    """
    today = datetime.now().strftime("%Y-%m-%d")
    confirmed_count = 0
    
    for category in funds_config["funds"]:
        for fund in funds_config["funds"][category]:
            # 获取待确认订单列表（支持多笔待确认）
            pending_orders = fund.get("pending_orders", [])
            if not pending_orders:
                continue
            
            # 保留未确认的订单
            remaining_orders = []
            
            for order in pending_orders:
                # 获取订单信息
                pending_amount = order.get("amount", 0.0)
                net_value_date = order.get("net_value_date")
                
                if pending_amount <= 0 or not net_value_date:
                    continue
                
                # 检查净值是否可用
                if not net_values or fund["code"] not in net_values:
                    remaining_orders.append(order)
                    continue
                
                # 获取当前获取到的净值日期
                current_net_value_date = net_values[fund["code"]].get("date")
                
                # 判断是否可以确认：当获取到的净值日期 >= 所需的净值日期时，即可确认
                if not current_net_value_date or current_net_value_date < net_value_date:
                    remaining_orders.append(order)
                    continue
                
                # 获取净值日期对应的净值
                order_net_value = net_values[fund["code"]]["net_value"]
                
                # 实际确认份额 = 待确认金额 / 净值日期的净值
                actual_shares = pending_amount / order_net_value
                
                shares = fund.get("shares", 0.0)
                cost_price = fund.get("cost_price", 0.0)
                
                if shares > 0:
                    # 摊薄成本价
                    new_cost_price = (shares * cost_price + actual_shares * order_net_value) / (shares + actual_shares)
                    fund["cost_price"] = round(new_cost_price, 4)
                else:
                    fund["cost_price"] = order_net_value
                
                fund["shares"] = round(shares + actual_shares, 4)
                confirmed_count += 1
            
            # 更新待确认订单列表（只保留未确认的）
            fund["pending_orders"] = remaining_orders
    
    return confirmed_count

def sync_today_pending_orders_from_history(funds_config):
    """从今日定投历史同步待确认订单到持仓配置，避免历史已写入但配置未体现"""
    today = datetime.now().strftime("%Y-%m-%d")
    history = load_invest_history()
    synced_count = 0
    
    for record in history:
        if record.get("date") != today:
            continue
        
        for txn in record.get("transactions", []):
            if txn.get("status") != "pending":
                continue
            
            code = txn.get("code")
            amount = round(float(txn.get("amount", 0)), 2)
            pending_date = txn.get("date", today)
            net_value_date = txn.get("net_value_date")
            category = txn.get("category") or find_fund_category(funds_config, code)
            
            if not code or amount <= 0 or not net_value_date or not category:
                continue
            
            funds = funds_config["funds"].setdefault(category, [])
            fund = next((item for item in funds if item.get("code") == code), None)
            if fund is None:
                fund = {
                    "code": code,
                    "name": txn.get("name", code),
                    "shares": 0.0,
                    "cost_price": float(txn.get("net_value", 0) or 0),
                    "pending_orders": []
                }
                funds.append(fund)
            
            pending_orders = fund.setdefault("pending_orders", [])
            exists = any(
                round(float(order.get("amount", 0)), 2) == amount
                and order.get("pending_date") == pending_date
                and order.get("net_value_date") == net_value_date
                for order in pending_orders
            )
            
            if not exists:
                pending_orders.append({
                    "amount": amount,
                    "pending_date": pending_date,
                    "net_value_date": net_value_date
                })
                synced_count += 1
    
    return synced_count


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
    
    # 计算净值日期：15:00前=T，15:00后=T+1
    if after_15h:
        net_value_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        net_value_date = today
    
    print(f"申购日期: {today}, 净值日期: {net_value_date}")
    
    total_amount = 0
    transactions = []
    
    for fund_plan in auto_invest_funds:
        code = fund_plan["code"].strip()
        amount = fund_plan["amount"]
        
        if amount > 0 and code and code in net_values:
            net_value = net_values[code]["net_value"]
            shares_to_buy = amount / net_value
            
            fund_name = net_values[code].get("name", code)
            
            category = find_fund_category(funds_config, code, auto_invest_funds)
            
            # 根据基金类型计算确认日期
            confirm_date = get_fund_confirm_date(today, category, after_15h=after_15h)
            
            if category:
                funds_list = funds_config["funds"].get(category, [])
                found = False
                for fund in funds_list:
                    if fund["code"] == code:
                        # 将新申购金额添加到待确认订单列表
                        pending_orders = fund.get("pending_orders", [])
                        pending_orders.append({
                            "amount": round(amount, 2),
                            "pending_date": today,  # 申购日期
                            "net_value_date": net_value_date  # 净值日期（用于确认时获取对应净值）
                        })
                        fund["pending_orders"] = pending_orders
                        found = True
                        break
                if not found:
                    funds_config["funds"][category].append({
                        "code": code,
                        "name": fund_name,
                        "shares": 0.0,
                        "cost_price": net_value,
                        "pending_orders": [{
                            "amount": round(amount, 2),
                            "pending_date": today,  # 申购日期
                            "net_value_date": net_value_date  # 净值日期
                        }]
                    })
            
            total_amount += amount
            
            transactions.append({
                "date": today,
                "confirm_date": confirm_date,
                "net_value_date": net_value_date,  # 记录净值日期
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
        
        if not force:
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
        
        # 保存基金配置（包含待确认金额）
        save_config(funds_config)
    
    return transactions, total_amount

def check_and_execute_auto_invest(funds_config, net_values, force=False):
    auto_config = load_auto_invest_config()
    
    if force or should_auto_invest_now(auto_config):
        auto_invest_funds = auto_config.get("auto_invest_funds", [])
        return execute_auto_invest(funds_config, net_values, auto_invest_funds, force=force)
    
    return None, 0

def find_fund_category(funds_config, code, auto_invest_funds=None):
    for category, funds in funds_config["funds"].items():
        for fund in funds:
            if fund["code"] == code:
                return category

    if auto_invest_funds:
        for fund_plan in auto_invest_funds:
            if fund_plan.get("code") == code:
                return fund_plan.get("category", "dividend")

    return None