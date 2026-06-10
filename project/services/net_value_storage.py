from datetime import date, datetime
from services.database import (
    load_net_value_history_db,
    save_net_value_history_db,
    upsert_nav,
    get_nav_by_record_date,
    get_fund_history_db
)


def load_net_value_history():
    return load_net_value_history_db()


def save_net_value_history(history):
    save_net_value_history_db(history)


def batch_save_net_value_history(fund_code, new_history):
    """批量保存基金历史净值，合并到数据库"""
    for date_str, data in new_history.items():
        upsert_nav(
            fund_code=fund_code,
            record_date=date_str,
            nav_date=data["date"],
            net_value=data["net_value"],
            change=data["change"],
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )


def get_today_str():
    return date.today().strftime("%Y-%m-%d")


def get_net_value_from_history(fund_code):
    return get_nav_by_record_date(fund_code, get_today_str())


def save_net_value_to_history(fund_code, net_value_data):
    nav_date = net_value_data["date"].strftime("%Y-%m-%d") if hasattr(net_value_data["date"], "strftime") else str(net_value_data["date"])
    upsert_nav(
        fund_code=fund_code,
        record_date=get_today_str(),
        nav_date=nav_date,
        net_value=net_value_data["net_value"],
        change=net_value_data["change"],
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source=net_value_data.get("source")
    )


def get_fund_history_data(fund_code):
    return get_fund_history_db(fund_code)
