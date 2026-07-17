import akshare as ak
import pandas as pd
import time
import requests
import json
from datetime import datetime, timedelta
from functools import lru_cache
from services.net_value_storage import get_net_value_from_history, save_net_value_to_history

# 蛋卷基金估值数据接口
DANJUAN_VALUATION_URL = "https://danjuanfunds.com/djapi/valuation/"


@lru_cache(maxsize=1)
def _get_all_fund_names():
    """获取所有基金代码→名称的映射（带缓存，避免重复请求）"""
    try:
        df = ak.fund_name_em()
        return dict(zip(df["基金代码"], df["基金简称"]))
    except Exception as e:
        print(f"获取基金名称列表失败: {e}")
        return {}


def get_fund_name_by_code(fund_code):
    """根据基金代码获取基金简称"""
    name_map = _get_all_fund_names()
    return name_map.get(fund_code)


def get_fund_net_value_from_akshare(fund_code):
    """从 AkShare 获取基金净值"""
    try:
        fund_em_open_fund_info_df = ak.fund.fund_em.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if not fund_em_open_fund_info_df.empty:
            latest = fund_em_open_fund_info_df.iloc[-1]
            return {
                "code": fund_code,
                "date": str(latest["净值日期"]),
                "net_value": float(latest["单位净值"]),
                "change": float(latest["日增长率"]),
                "source": "akshare"
            }
        return None
    except Exception as e:
        print(f"AkShare 获取基金 {fund_code} 净值失败: {e}")
        return None

def get_fund_net_value_from_eastmoney(fund_code):
    """从天天基金网获取基金净值（备用数据源）"""
    try:
        url = f"https://fund.eastmoney.com/f10/F10DataApi.aspx?type=lsjz&code={fund_code}&page=1&per=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"https://fund.eastmoney.com/{fund_code}.html"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = "utf-8"
        
        content = response.text
        if "lsjz" not in content:
            return None
        
        import re
        match = re.search(r'var\s+lsjz\s*=\s*(\[.*?\]);', content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if data:
                    latest = data[0]
                    return {
                        "code": fund_code,
                        "date": str(latest.get("FSRQ", "")),
                        "net_value": float(latest.get("DWJZ", "0")),
                        "change": float(latest.get("JZZZL", "0")),
                        "source": "eastmoney"
                    }
            except Exception as e:
                print(f"解析天天基金数据失败: {e}")
        
        return None
    except Exception as e:
        print(f"天天基金获取基金 {fund_code} 净值失败: {e}")
        return None

def get_fund_net_value(fund_code, use_cache=True):
    """获取基金净值，实现双源fallback机制：AkShare → 天天基金 → 历史缓存"""
    
    # 根据基金代码判断类型
    # A股基金：晚上10点可以拿到当天净值
    # 美股基金（如纳指ETF）：晚上10点只能拿到前一天净值（因为美股收盘晚）
    is_us_fund = _is_us_etf(fund_code)
    
    # 检查缓存数据的新鲜度
    if use_cache:
        cached_data = get_net_value_from_history(fund_code)
        if cached_data:
            # 检查净值日期是否是最近的
            from datetime import datetime, timedelta
            net_value_date = datetime.strptime(cached_data["date"], "%Y-%m-%d")
            today = datetime.now()
            
            # 根据基金类型确定最大允许延迟
            max_delay = 0 if not is_us_fund else 1  # A股0天，美股1天
            
            days_diff = (today - net_value_date).days
            if days_diff <= max_delay:
                return {
                    "code": fund_code,
                    "date": cached_data["date"],
                    "net_value": cached_data["net_value"],
                    "change": cached_data["change"],
                    "source": "cache"
                }
            else:
                # 净值日期太旧，尝试获取最新数据
                if is_us_fund:
                    print(f"[INFO] 基金 {fund_code} (美股) 缓存净值日期({cached_data['date']})已过期，尝试获取最新数据")
                else:
                    print(f"[INFO] 基金 {fund_code} (A股) 缓存净值日期({cached_data['date']})已过期，尝试获取最新数据")

    # 数据源优先级：AkShare → 天天基金 → 历史缓存
    data_sources = [
        ("akshare", get_fund_net_value_from_akshare),
        ("eastmoney", get_fund_net_value_from_eastmoney)
    ]
    
    for source_name, source_func in data_sources:
        result = source_func(fund_code)
        if result and result.get("net_value", 0) > 0:
            save_net_value_to_history(fund_code, result)
            return result
        time.sleep(0.2)

    # 所有数据源都失败，使用历史缓存兜底
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


def _is_us_etf(fund_code):
    """
    判断是否是投资美股的ETF
    
    规则：
    - 纳指类基金（nasdaq）：投资美股，晚上10点只能拿到前一天净值
    - 红利类基金（dividend）：A股，晚上10点可以拿到当天净值
    - 黄金类基金（gold）：可能是A股或现货，晚上10点可以拿到当天净值
    """
    try:
        from services.storage import load_config
        
        config = load_config()
        
        # 检查基金属于哪个类别
        for category in ["nasdaq", "dividend", "gold"]:
            for fund in config["funds"].get(category, []):
                if fund.get("code") == fund_code:
                    # 纳指类基金是投资美股
                    if category == "nasdaq":
                        return True
                    else:
                        return False
        
        # 如果配置中没有找到，默认为A股
        return False
        
    except Exception as e:
        # 如果读取配置失败，默认为A股
        print(f"[WARN] 无法判断基金类型: {fund_code}, 默认为A股")
        return False

def get_fund_batch_net_value(fund_codes, use_cache=True):
    results = {}
    source_stats = {
        "akshare": [],
        "eastmoney": [],
        "cache": [],
        "cache_fallback": [],
        "failed": []
    }

    for code in fund_codes:
        data = get_fund_net_value(code, use_cache)
        if data:
            results[code] = data
            source = data.get("source", "unknown")
            if source in source_stats:
                source_stats[source].append(code)
            else:
                source_stats["failed"].append(code)
        else:
            source_stats["failed"].append(code)
        time.sleep(0.3)

    # 输出数据源统计信息
    print("\n=== 净值获取数据源统计 ===")
    print(f"AkShare: {len(source_stats['akshare'])} 只")
    print(f"天天基金: {len(source_stats['eastmoney'])} 只")
    print(f"缓存(优先): {len(source_stats['cache'])} 只")
    print(f"缓存(兜底): {len(source_stats['cache_fallback'])} 只")
    print(f"获取失败: {len(source_stats['failed'])} 只")
    
    if source_stats["eastmoney"]:
        print(f"使用天天基金的基金: {', '.join(source_stats['eastmoney'])}")
    if source_stats["cache_fallback"]:
        print(f"使用缓存兜底的基金: {', '.join(source_stats['cache_fallback'])}")
    if source_stats["failed"]:
        print(f"获取失败的基金: {', '.join(source_stats['failed'])}")

    return results

def check_data_freshness(net_values):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    fresh_count = 0
    cache_count = 0
    source_counts = {
        "akshare": 0,
        "eastmoney": 0,
        "cache": 0,
        "cache_fallback": 0
    }

    for code, data in net_values.items():
        # 允许今天或昨天的数据作为新鲜数据
        # 因为基金净值通常在当天晚上公布，当天白天显示的是昨天的净值
        data_date = data.get("date")
        if data_date == today or data_date == yesterday:
            fresh_count += 1
        else:
            cache_count += 1
        
        source = data.get("source", "unknown")
        if source in source_counts:
            source_counts[source] += 1

    return {
        "total": len(net_values),
        "fresh": fresh_count,
        "cached": cache_count,
        "all_fresh": fresh_count == len(net_values),
        "sources": source_counts
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

def get_fund_history_net_value_from_akshare(fund_code, start_date=None, end_date=None):
    """从 AkShare 获取基金历史净值"""
    try:
        fund_em_open_fund_info_df = ak.fund.fund_em.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if not fund_em_open_fund_info_df.empty:
            # 设置默认日期范围为基金成立以来
            if not end_date:
                end_date = datetime.now().strftime("%Y-%m-%d")
            
            # 筛选日期范围内的数据
            fund_em_open_fund_info_df["净值日期"] = pd.to_datetime(fund_em_open_fund_info_df["净值日期"])
            mask = fund_em_open_fund_info_df["净值日期"] <= end_date
            if start_date:
                mask &= fund_em_open_fund_info_df["净值日期"] >= start_date
            filtered_df = fund_em_open_fund_info_df.loc[mask]
            
            history = {}
            for _, row in filtered_df.iterrows():
                date_str = str(row["净值日期"].date())
                history[date_str] = {
                    "date": date_str,
                    "net_value": float(row["单位净值"]),
                    "change": float(row["日增长率"]),
                    "source": "akshare"
                }
            
            return history
        return None
    except Exception as e:
        print(f"AkShare 获取基金 {fund_code} 历史净值失败: {e}")
        return None

def get_fund_history_net_value_from_eastmoney(fund_code, start_date=None, end_date=None):
    """从天天基金网获取基金历史净值（备用数据源）"""
    try:
        # 设置默认日期范围为基金成立以来
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        # 计算需要获取的页数（每页20条）
        url = f"https://fund.eastmoney.com/f10/F10DataApi.aspx?type=lsjz&code={fund_code}&page=1&per=20"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"https://fund.eastmoney.com/{fund_code}.html"
        }
        
        history = {}
        page = 1
        
        while True:
            url = f"https://fund.eastmoney.com/f10/F10DataApi.aspx?type=lsjz&code={fund_code}&page={page}&per=20"
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = "utf-8"
            
            content = response.text
            if "lsjz" not in content:
                break
            
            import re
            match = re.search(r'var\s+lsjz\s*=\s*(\[.*?\]);', content, re.DOTALL)
            if not match:
                break
            
            try:
                data = json.loads(match.group(1))
                if not data:
                    break
                
                has_data = False
                for item in data:
                    date_str = str(item.get("FSRQ", ""))
                    if not date_str:
                        continue
                    
                    # 检查日期是否在范围内
                    if start_date and date_str < start_date:
                        continue
                    if date_str > end_date:
                        continue
                    
                    net_value = float(item.get("DWJZ", "0"))
                    if net_value > 0:
                        history[date_str] = {
                            "date": date_str,
                            "net_value": net_value,
                            "change": float(item.get("JZZZL", "0")),
                            "source": "eastmoney"
                        }
                        has_data = True
                
                # 如果当前页没有数据或日期超出范围，停止
                if not has_data or (start_date and date_str < start_date):
                    break
                
                page += 1
                time.sleep(0.2)
                
            except Exception as e:
                print(f"解析天天基金历史数据失败: {e}")
                break
        
        return history if history else None
    
    except Exception as e:
        print(f"天天基金获取基金 {fund_code} 历史净值失败: {e}")
        return None

def get_fund_history_net_value(fund_code, start_date=None, end_date=None):
    """获取基金历史净值，实现双源fallback机制：AkShare → 天天基金"""
    # 设置默认日期范围为基金成立以来
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    # 数据源优先级：AkShare → 天天基金
    data_sources = [
        ("akshare", get_fund_history_net_value_from_akshare),
        ("eastmoney", get_fund_history_net_value_from_eastmoney)
    ]
    
    for source_name, source_func in data_sources:
        result = source_func(fund_code, start_date, end_date)
        if result and len(result) > 0:
            print(f"获取基金 {fund_code} 历史净值成功，共 {len(result)} 条记录")
            return result
        time.sleep(0.2)
    
    print(f"获取基金 {fund_code} 历史净值失败")
    return None

def batch_update_history_net_value(fund_codes):
    """批量更新基金历史净值"""
    print("\n=== 开始批量更新历史净值 ===")
    
    for code in fund_codes:
        print("处理基金: %s" % code)
        history = get_fund_history_net_value(code)
        
        if history:
            # 保存到历史文件
            from services.net_value_storage import batch_save_net_value_history
            batch_save_net_value_history(code, history)
            print("基金 %s 历史净值更新完成，共 %d 条记录" % (code, len(history)))
        else:
            print("基金 %s 历史净值获取失败" % code)
        
        time.sleep(0.3)
    
    print("\n=== 批量更新完成 ===")

def get_danjuan_index_pe(index_code="NDX"):
    """从蛋卷基金爬取指数PE数据
    
    由于蛋卷基金API需要登录，此函数会尝试多种数据源作为备选。
    
    Args:
        index_code: 指数代码，如 NDX(纳斯达克100), SPX(标普500), HS300(沪深300) 等
    
    Returns:
        dict: PE数据，包含 pe, pe_percentile, pb, pb_percentile 等字段
    """
    # 尝试不同的数据源
    data_sources = [
        ("eastmoney", lambda: _get_pe_from_eastmoney(index_code)),
        ("qqq_alpha", lambda: _get_qqq_pe_from_alpha_vantage()),
        ("simulated", lambda: _get_simulated_pe(index_code))
    ]
    
    for source_name, source_func in data_sources:
        try:
            result = source_func()
            if result and result.get("pe", 0) > 0:
                print("从%s获取%s PE数据成功" % (result.get('data_source', source_name), index_code))
                return result
        except Exception as e:
            print("从%s获取%s PE数据失败: %s" % (source_name, index_code, e))
    
    print("无法获取%s PE数据，返回模拟数据" % index_code)
    return _get_simulated_pe(index_code)

def _get_pe_from_eastmoney(index_code="NDX"):
    """从东方财富获取指数PE数据"""
    try:
        # 东方财富市场代码映射
        market_map = {
            "NDX": "100.NDX",
            "SPX": "100.SPX",
            "HS300": "000300.SH"
        }
        
        secid = market_map.get(index_code, f"100.{index_code}")
        url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f62,f116,f169,f170,f177,f183,f184"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://quote.eastmoney.com/"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        
        if data.get("data"):
            d = data["data"]
            return {
                "index_code": index_code,
                "index_name": d.get("f58", ""),
                "pe": float(d.get("f116", 0)) if d.get("f116") else 0,
                "pe_percentile": 0,  # 东方财富不直接提供百分位
                "pb": float(d.get("f169", 0)) if d.get("f169") else 0,
                "pb_percentile": 0,
                "dividend_yield": float(d.get("f177", 0)) / 100 if d.get("f177") else 0,
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_source": "东方财富"
            }
        return None
    except Exception as e:
        print(f"东方财富获取PE失败: {e}")
        return None

def _get_qqq_pe_from_alpha_vantage():
    """从Alpha Vantage获取QQQ的PE数据作为纳指替代"""
    try:
        api_key = "3JAN3WHV3Q87LVDP"
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol=QQQ&apikey={api_key}"
        
        response = requests.get(url, timeout=15)
        data = response.json()
        
        if data and data.get("TrailingPE"):
            return {
                "index_code": "NDX",
                "index_name": "纳斯达克100(QQQ替代)",
                "pe": float(data["TrailingPE"]),
                "pe_percentile": 0,  # Alpha Vantage不提供百分位
                "pb": float(data.get("PriceToBookRatio", 0)),
                "pb_percentile": 0,
                "dividend_yield": float(data.get("DividendYield", 0)),
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_source": "Alpha Vantage(QQQ)"
            }
        return None
    except Exception as e:
        print(f"Alpha Vantage获取PE失败: {e}")
        return None

def _get_simulated_pe(index_code="NDX"):
    """生成模拟PE数据作为兜底方案"""
    # 基于历史数据的模拟值
    simulated_data = {
        "NDX": {
            "name": "纳斯达克100",
            "pe": 36.0,
            "pe_percentile": 82.96,
            "pb": 6.8,
            "pb_percentile": 85.0,
            "dividend_yield": 0.5
        },
        "SPX": {
            "name": "标普500",
            "pe": 21.5,
            "pe_percentile": 65.0,
            "pb": 3.8,
            "pb_percentile": 70.0,
            "dividend_yield": 1.5
        },
        "HS300": {
            "name": "沪深300",
            "pe": 12.5,
            "pe_percentile": 35.0,
            "pb": 1.5,
            "pb_percentile": 40.0,
            "dividend_yield": 2.5
        }
    }
    
    data = simulated_data.get(index_code, simulated_data["NDX"])
    
    return {
        "index_code": index_code,
        "index_name": data["name"],
        "pe": data["pe"],
        "pe_percentile": data["pe_percentile"],
        "pb": data["pb"],
        "pb_percentile": data["pb_percentile"],
        "dividend_yield": data["dividend_yield"],
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "模拟数据"
    }

def get_danjuan_index_pe_history(index_code="NDX", days=365):
    """获取指数PE历史数据
    
    由于蛋卷基金API需要登录，此函数会尝试多种数据源作为备选。
    
    Args:
        index_code: 指数代码
        days: 获取多少天的历史数据
    
    Returns:
        list: PE历史数据列表，每个元素包含 date, pe, pe_percentile
    """
    # 尝试蛋卷基金API
    try:
        url = f"{DANJUAN_VALUATION_URL}{index_code}/history"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://danjuanfunds.com/dj-valuation-table-detail/{index_code}"
        }
        
        response = requests.get(url, headers=headers, params={"days": days}, timeout=15)
        data = response.json()
        
        if data.get("code") == 0 and data.get("data"):
            history = []
            for item in data["data"]:
                history.append({
                    "date": item.get("date", ""),
                    "pe": float(item.get("pe", 0)),
                    "pe_percentile": float(item.get("pe_percentile", 0)),
                    "pb": float(item.get("pb", 0)),
                    "pb_percentile": float(item.get("pb_percentile", 0))
                })
            print("从蛋卷基金获取%s PE历史数据成功" % index_code)
            return history
    except Exception as e:
        print("蛋卷基金获取PE历史数据失败: %s" % e)
    
    # 返回模拟历史数据作为兜底
    print("使用模拟数据作为%s PE历史数据" % index_code)
    return _generate_simulated_pe_history(index_code, days)

def _generate_simulated_pe_history(index_code="NDX", days=365):
    """生成模拟PE历史数据"""
    base_data = {
        "NDX": {"pe_mean": 32, "pe_std": 4, "pb_mean": 6.2, "pb_std": 0.8},
        "SPX": {"pe_mean": 20, "pe_std": 3, "pb_mean": 3.5, "pb_std": 0.5},
        "HS300": {"pe_mean": 12, "pe_std": 2, "pb_mean": 1.4, "pb_std": 0.2}
    }
    
    data = base_data.get(index_code, base_data["NDX"])
    history = []
    
    import random
    from datetime import datetime, timedelta
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # 生成趋势（模拟纳指上升趋势）
    trend = 0.02  # 轻微上升趋势
    
    current_pe = data["pe_mean"]
    current_pb = data["pb_mean"]
    
    # 计算历史百分位范围（基于模拟数据）
    pe_min = data["pe_mean"] - data["pe_std"] * 2
    pe_max = data["pe_mean"] + data["pe_std"] * 2
    
    date = start_date
    while date <= end_date:
        # 随机波动
        pe_change = (random.random() - 0.5) * data["pe_std"] * 0.4
        pb_change = (random.random() - 0.5) * data["pb_std"] * 0.4
        
        current_pe = max(pe_min, min(pe_max, current_pe + pe_change + trend))
        current_pb = max(data["pb_mean"] - data["pb_std"] * 2, 
                        min(data["pb_mean"] + data["pb_std"] * 2, 
                            current_pb + pb_change))
        
        # 计算百分位
        pe_percentile = ((current_pe - pe_min) / (pe_max - pe_min)) * 100
        
        # 只保留工作日数据
        if date.weekday() < 5:
            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "pe": round(current_pe, 2),
                "pe_percentile": round(min(100, max(0, pe_percentile)), 2),
                "pb": round(current_pb, 2),
                "pb_percentile": round(min(100, max(0, ((current_pb - (data["pb_mean"] - data["pb_std"] * 2)) / (data["pb_std"] * 4)) * 100)), 2)
            })
        
        date += timedelta(days=1)
    
    # 确保最后一个数据点与当前模拟PE一致
    if history and index_code == "NDX":
        latest_pe = get_danjuan_index_pe(index_code)
        if latest_pe and latest_pe.get("pe", 0) > 0:
            history[-1]["pe"] = latest_pe["pe"]
            history[-1]["pe_percentile"] = latest_pe.get("pe_percentile", history[-1]["pe_percentile"])
    
    return history