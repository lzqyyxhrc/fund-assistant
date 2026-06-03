DEFAULT_REBALANCE_THRESHOLD = 0.02

def calculate_category_value(funds, net_values):
    """计算各分类的市值（仅计算已确认份额，不包含待确认份额）
    
    QDII基金采用T+2确认机制，新申购份额在确认前不计入市值计算，
    以避免再平衡判断失准。
    
    Args:
        funds: 基金配置字典
        net_values: 净值数据字典
        
    Returns:
        dict: 各分类的市值
    """
    category_values = {}
    for category, fund_list in funds.items():
        total_value = 0
        for fund in fund_list:
            if fund["code"] in net_values:
                # 只计算已确认份额(shares)，不包含待确认份额(pending_shares)
                confirmed_shares = fund.get("shares", 0.0)
                total_value += confirmed_shares * net_values[fund["code"]]["net_value"]
        category_values[category] = total_value
    return category_values

def calculate_total_value(category_values):
    return sum(category_values.values())

def calculate_total_portfolio_value(category_values):
    return sum(category_values.values())

def calculate_current_weights(category_values, total_value):
    if total_value == 0:
        return {k: 0 for k in category_values.keys()}
    return {k: v / total_value for k, v in category_values.items()}

def calculate_target_values(targets, total_value, new_investment):
    total_with_new = total_value + new_investment
    return {k: total_with_new * v for k, v in targets.items()}

def calculate_deviation(current_weights, targets):
    deviations = {}
    for category, target_weight in targets.items():
        current_weight = current_weights.get(category, 0)
        deviations[category] = current_weight - target_weight
    return deviations

def is_rebalance_needed(deviations, threshold=None):
    if threshold is None:
        threshold = DEFAULT_REBALANCE_THRESHOLD
    for category, deviation in deviations.items():
        if abs(deviation) > threshold:
            return True
    return False

def calculate_rebalancing_amounts(targets, category_values, total_value, new_investment, threshold=None):
    if threshold is None:
        threshold = DEFAULT_REBALANCE_THRESHOLD
    current_weights = calculate_current_weights(category_values, total_value)
    deviations = calculate_deviation(current_weights, targets)
    
    if not is_rebalance_needed(deviations, threshold):
        return {category: new_investment * targets[category] for category in targets.keys()}
    
    total_with_new = total_value + new_investment

    underweight_categories = {}
    overweight_categories = {}

    for category, target_weight in targets.items():
        current_value = category_values.get(category, 0)
        target_value = total_with_new * target_weight
        amount_needed = target_value - current_value

        if amount_needed > 0:
            underweight_categories[category] = {
                "amount_needed": amount_needed,
                "deviation": deviations[category]
            }
        else:
            overweight_categories[category] = {
                "amount_needed": abs(amount_needed),
                "deviation": deviations[category]
            }

    total_underweight = sum(c["amount_needed"] for c in underweight_categories.values())
    total_overweight = sum(c["amount_needed"] for c in overweight_categories.values())

    if total_underweight > 0:
        amounts = {category: 0 for category in targets.keys()}

        for category, info in underweight_categories.items():
            priority = info["deviation"]
            base_amount = (info["amount_needed"] / total_underweight) * new_investment
            amounts[category] = base_amount * (1 + abs(priority) * 2)

        total_allocated = sum(amounts.values())
        if total_allocated > new_investment:
            scale = new_investment / total_allocated
            for category in amounts:
                amounts[category] *= scale
    elif total_overweight > 0:
        amounts = {category: new_investment / len(targets) for category in targets.keys()}
    else:
        amounts = {category: new_investment / len(targets) for category in targets.keys()}

    return amounts

def distribute_amount_to_funds(amount, funds, net_values):
    if not funds:
        return []

    total_shares = sum(f["shares"] for f in funds)
    if total_shares == 0:
        total_shares = 1

    allocations = []
    for fund in funds:
        if fund["code"] in net_values:
            ratio = fund["shares"] / total_shares
            allocation = amount * ratio
            shares_to_buy = allocation / net_values[fund["code"]]["net_value"]
            allocations.append({
                "code": fund["code"],
                "name": fund["name"],
                "amount": allocation,
                "shares": shares_to_buy,
                "net_value": net_values[fund["code"]]["net_value"]
            })

    return allocations
