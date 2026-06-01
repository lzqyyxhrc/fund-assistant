import akshare as ak
import pandas as pd
import time
import requests
import json
from datetime import datetime, timedelta
from services.net_value_storage import get_net_value_from_history, save_net_value_to_history

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
    
    # 优先从缓存读取（如果启用）
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
    fresh_count = 0
    cache_count = 0
    source_counts = {
        "akshare": 0,
        "eastmoney": 0,
        "cache": 0,
        "cache_fallback": 0
    }

    for code, data in net_values.items():
        if data.get("date") == today:
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
            # 设置默认日期范围为今年以来
            if not start_date:
                start_date = datetime.now().strftime("%Y-01-01")
            if not end_date:
                end_date = datetime.now().strftime("%Y-%m-%d")
            
            # 筛选日期范围内的数据
            fund_em_open_fund_info_df["净值日期"] = pd.to_datetime(fund_em_open_fund_info_df["净值日期"])
            mask = (fund_em_open_fund_info_df["净值日期"] >= start_date) & (fund_em_open_fund_info_df["净值日期"] <= end_date)
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
        # 设置默认日期范围为今年以来
        if not start_date:
            start_date = datetime.now().strftime("%Y-01-01")
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
                    if date_str < start_date:
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
                if not has_data or date_str < start_date:
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
    # 设置默认日期范围为今年以来
    if not start_date:
        start_date = datetime.now().strftime("%Y-01-01")
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
        print(f"\n处理基金: {code}")
        history = get_fund_history_net_value(code)
        
        if history:
            # 保存到历史文件
            from services.net_value_storage import batch_save_net_value_history
            batch_save_net_value_history(code, history)
            print(f"✅ 基金 {code} 历史净值更新完成，共 {len(history)} 条记录")
        else:
            print(f"❌ 基金 {code} 历史净值获取失败")
        
        time.sleep(0.3)
    
    print("\n=== 批量更新完成 ===")