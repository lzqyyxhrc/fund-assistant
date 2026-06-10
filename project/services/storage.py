from services.database import (
    load_config_db,
    save_config_db,
    load_auto_invest_config_db,
    save_auto_invest_config_db,
    load_invest_history_db,
    save_invest_history_db,
    load_net_value_history_db,
    save_net_value_history_db,
    get_setting,
    set_setting
)


def load_config():
    return load_config_db()


def save_config(config):
    save_config_db(config)


def load_auto_invest_config():
    return load_auto_invest_config_db()


def save_auto_invest_config(config):
    save_auto_invest_config_db(config)


def load_invest_history():
    return load_invest_history_db()


def save_invest_history(history):
    save_invest_history_db(history)


def load_net_value_history():
    return load_net_value_history_db()


def save_net_value_history(history):
    save_net_value_history_db(history)


def load_investment_amount():
    return get_setting("investment_amount", 1000)


def save_investment_amount(amount):
    set_setting("investment_amount", amount)


def load_threshold():
    return get_setting("rebalance_threshold", 0.02)


def save_threshold(threshold):
    set_setting("rebalance_threshold", threshold)


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


__all__ = [
    'load_config', 'save_config',
    'load_auto_invest_config', 'save_auto_invest_config',
    'load_invest_history', 'save_invest_history',
    'load_net_value_history', 'save_net_value_history',
    'load_investment_amount', 'save_investment_amount',
    'load_threshold', 'save_threshold',
    'get_category_names', 'get_category_color',
]