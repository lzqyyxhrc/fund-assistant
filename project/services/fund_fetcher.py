import akshare as ak
import pandas as pd
import time
from datetime import datetime, timedelta
from services.net_value_storage import get_net_value_from_history, save_net_value_to_history

def get_fund_net_value(fund_code, use_cache=True):
    if use_cache:
        cached_data = get_net_value_from_history(fund_code)
        if cached_data:
            return {
                "code": fund_code,
                "date": cached_data["date"],
                "net_value": cached_data["net_value"],
                "change": cached_data["change"],
                "source": "cache"
            }

    try:
        fund_em_open_fund_info_df = ak.fund.fund_em.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")

        if not fund_em_open_fund_info_df.empty:
            latest = fund_em_open_fund_info_df.iloc[-1]
            result = {
                "code": fund_code,
                "date": str(latest["净值日期"]),
                "net_value": float(latest["单位净值"]),
                "change": float(latest["日增长率"]),
                "source": "realtime"
            }
            save_net_value_to_history(fund_code, result)
            return result
        return None
    except Exception as e:
        print(f"获取基金 {fund_code} 净值失败: {e}")
        if use_cache:
            cached_data = get_net_value_from_history(fund_code)
            if cached_data:
                return {
                    "code": fund_code,
                    "date": cached_data["date"],
                    "net_value": cached_data["net_value"],
                    "change": cached_data["change"],
                    "source": "cache_fallback"
                }
        return None

def get_fund_batch_net_value(fund_codes, use_cache=True):
    results = {}
    cache_used_codes = []
    failed_codes = []

    for code in fund_codes:
        data = get_fund_net_value(code, use_cache)
        if data:
            results[code] = data
            if data.get("source") in ["cache", "cache_fallback"]:
                cache_used_codes.append(code)
        else:
            failed_codes.append(code)
        time.sleep(0.3)

    if cache_used_codes:
        print(f"警告: 以下基金使用历史缓存数据: {', '.join(cache_used_codes)}")
    if failed_codes:
        print(f"错误: 以下基金获取失败: {', '.join(failed_codes)}")

    return results

def check_data_freshness(net_values):
    today = datetime.now().strftime("%Y-%m-%d")
    fresh_count = 0
    cache_count = 0

    for code, data in net_values.items():
        if data.get("date") == today:
            fresh_count += 1
        else:
            cache_count += 1

    return {
        "total": len(net_values),
        "fresh": fresh_count,
        "cached": cache_count,
        "all_fresh": fresh_count == len(net_values)
    }

def get_fund_info(fund_code):
    try:
        fund_em_fund_name_df = ak.fund_em_fund_name()
        fund_info = fund_em_fund_name_df[fund_em_fund_name_df["基金代码"] == fund_code]
        if not fund_info.empty:
            return {
                "code": fund_code,
                "name": fund_info.iloc[0]["基金名称"],
                "type": fund_info.iloc[0]["基金类型"]
            }
        return {"code": fund_code, "name": "未知基金", "type": "未知类型"}
    except Exception as e:
        print(f"获取基金 {fund_code} 信息失败: {e}")
        return {"code": fund_code, "name": "未知基金", "type": "未知类型"}