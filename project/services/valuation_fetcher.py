"""
V2 估值指标数据获取服务
============================

三层架构：
  🧠 Layer 1：成分股估值（QQQ Top15 加权）
     - 取 QQQ 权重最大的15只成分股（覆盖 ~70-75%）
     - 每只股票拿 TTM PE/PB/PS
     - 按 QQQ 官方 ETF 权重加权（不是市值权重，更接近真实NDX）
  
  🧠 Layer 2：宏观修正
     - 10Y 国债利率 (DGS10)
     - 10Y 实际利率 (DFII10)
     - VIX 波动率指数 (VIXCLS)
     - 美元贸易加权指数 (DTWEXBGS)
     - Buffett 指标 (WILL5000PRFC / GDP)
  
  🧠 Layer 3：大类资产
     - 纳指：Top15 加权 PE/PB + Buffett
     - 红利：中证红利 PE + 股息率
     - 黄金：金银比 + 实际利率

免费 API 限制下的现实方案（2025-08-31 FMP API 变更后）：
  ✅ FMP /stable/ratios-ttm?symbol=XXX  → 个股 TTM PE/PB/PS（免费）
  ✅ FMP /stable/key-metrics-ttm?symbol=XXX → 个股 marketCap（免费）
  ✅ FRED 各类宏观时间序列（免费，需 API key）
  ❌ FMP ETF 持仓权重 endpoint → 付费或不存在（硬编码解决）
  ❌ FMP 历史 ratios（季度/年度）→ 付费（用常识区间+每天积累解决）

硬编码权重说明：
  QQQ 每季度末调仓，权重变化缓慢。
  取 Top15（占 70-75%）权重硬编码，每季手动更新。
  附 "权重更新日期" 字段作为提醒。
"""

import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests

from services.database import (
    upsert_valuation_metric,
    bulk_upsert_valuation_metrics,
    get_setting,
    set_setting,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

# ==================================================================
# FRED 宏观指标（series_id -> 元数据）
# ==================================================================
FRED_SERIES = {
    # 利率类
    "DGS10":      {"label": "10年期美国国债收益率(%)",   "asset": "macro", "metric": "treasury_10y"},
    "DFII10":     {"label": "10年期TIPS实际利率(%)",    "asset": "macro", "metric": "real_rate_10y"},
    "T10YIE":     {"label": "10年期盈亏平衡通胀率(%)",  "asset": "macro", "metric": "breakeven_10y"},
    "FEDFUNDS":   {"label": "联邦基金利率(%)",           "asset": "macro", "metric": "fed_funds_rate"},
    # 波动率
    "VIXCLS":     {"label": "VIX 波动率指数",            "asset": "macro", "metric": "vix"},
    # 货币与经济
    "M2SL":       {"label": "M2 货币供应量(十亿美元)",   "asset": "macro", "metric": "m2"},
    "CPIAUCSL":   {"label": "CPI 消费者物价指数",        "asset": "macro", "metric": "cpi"},
    "UNRATE":     {"label": "美国失业率(%)",             "asset": "macro", "metric": "unrate"},
    # Buffett Indicator 已停用：WILL5000PRFC 在FRED当前返回400，且核心评分不依赖该备用指标
    # "GDP":        {"label": "美国 GDP(十亿美元, 季度)",  "asset": "macro", "metric": "gdp"},
    # 美元指数
    "DTWEXBGS":   {"label": "美元贸易加权指数(广义)",    "asset": "macro", "metric": "dollar_index"},
    # 商品指数代理：PPIACO（生产者价格指数 All Commodities）
    # 注：Refinitiv CRB Index 需要付费数据源，PPI是FRED上免费稳定的替代方案
    "PPIACO":     {"label": "生产者价格指数(PPI)",       "asset": "macro", "metric": "commodity_index"},
}

# ==================================================================
# 基础工具
# ==================================================================

FMP_BASE = "https://financialmodelingprep.com/stable"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def get_api_key(key_name, default=None):
    val = get_setting(f"api_key:{key_name}", None)
    if val:
        return str(val).strip()
    import os
    env_val = os.environ.get(key_name.upper().replace("-", "_"))
    if env_val:
        return env_val.strip()
    return default


def set_api_key(key_name, value):
    set_setting(f"api_key:{key_name}", value.strip() if value else None)


def _http_get_json(url, params=None, timeout=20):
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        logger.error(f"返回非 JSON: {resp.text[:200]}")
        raise


# ==================================================================
# 蛋卷基金（雪球旗下）官方估值接口
# ==================================================================
# 提供 PE/PB/PEG/ROE/股息率 + 历史百分位，覆盖纳指/标普/中证红利等
# 需要登录 Cookie（xq_a_token 等），Cookie 过期会返回 401/重定向。
# Cookie 存在 setting: api_key:danjuan_cookie
# ==================================================================
DANJUAN_BASE = "https://danjuanfunds.com/djapi/index_eva"
DANJUAN_REFERER = "https://danjuanfunds.com/dj-valuation-table-detail"

# 指数代码映射：内部资产 → 蛋卷指数代码
DANJUAN_INDEX = {
    "nasdaq": "NDX",        # 纳指100
    "dividend": "SH000922", # 中证红利
}

# 历史指标名映射：(asset_type, kind) → metric_name（须与 valuation_scoring.METRIC_META 对齐）
DANJUAN_METRIC = {
    ("nasdaq", "pe"): "qqq_pe",
    ("nasdaq", "pb"): "qqq_pb",        # 纳指当前不计分，仅留存历史
    ("dividend", "pe"): "csi_div_pe",
    ("dividend", "pb"): "csi_div_pb",
}


def _danjuan_headers():
    cookie = get_api_key("danjuan_cookie", "")
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": DANJUAN_REFERER,
        "Cookie": cookie,
    }


def _danjuan_get(url):
    """请求蛋卷接口，返回 (data, error)。error 非空表示失败（含 cookie 过期）。"""
    try:
        resp = requests.get(url, headers=_danjuan_headers(), timeout=20)
    except Exception as e:
        return None, f"网络错误: {e}"

    if resp.status_code in (401, 403):
        return None, "cookie_expired"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"

    try:
        j = resp.json()
    except Exception:
        # 返回非 JSON（通常是登录页 HTML）→ Cookie 失效
        return None, "cookie_expired"

    if j.get("result_code") != 0:
        return None, f"接口错误码: {j.get('result_code')}"
    return j.get("data"), None


def _set_danjuan_status(ok, msg=""):
    """记录蛋卷接口状态，供前端展示。"""
    set_setting("danjuan:status", "ok" if ok else "error")
    set_setting("danjuan:status_msg", msg)
    set_setting("danjuan:status_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def fetch_danjuan_detail(index_code):
    """
    获取蛋卷指数当前估值快照。
    返回 dict: {pe, pb, peg, roe, dividend_yield, pe_percentile, pb_percentile, eva_type}
    或 (None, error)
    """
    data, err = _danjuan_get(f"{DANJUAN_BASE}/detail/{index_code}")
    if err:
        return None, err
    return {
        "pe": data.get("pe"),
        "pb": data.get("pb"),
        "peg": data.get("peg"),
        "roe": data.get("roe"),
        # yeild 是小数（0.0043），转成百分比
        "dividend_yield": (data.get("yeild") or 0) * 100,
        "pe_percentile": data.get("pe_percentile"),
        "pb_percentile": data.get("pb_percentile"),
        "eva_type": data.get("eva_type"),
        "ts": data.get("ts"),
    }, None


def fetch_danjuan_history(index_code, kind="pe"):
    """
    获取蛋卷指数历史序列。
    kind: "pe" 或 "pb"
    返回 ([(date_str, value), ...], error)
    """
    url = f"{DANJUAN_BASE}/{kind}_history/{index_code}?day=all"
    data, err = _danjuan_get(url)
    if err:
        return None, err
    key = f"index_eva_{kind}_growths"
    items = data.get(key) or []
    out = []
    for it in items:
        ts = it.get("ts")
        val = it.get(kind)
        if ts is None or val is None:
            continue
        date_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        out.append((date_str, float(val)))
    return out, None


def import_danjuan_history(asset_type, index_code, force=False):
    """
    导入某指数的 PE/PB 完整历史序列到数据库（一次性回填，约10年）。
    返回写入条数。
    """
    flag_key = f"danjuan_history_imported:{asset_type}"
    if not force and get_setting(flag_key, False):
        logger.info(f"{asset_type} 蛋卷历史已导入过，跳过（force=True 可重新导入）")
        return 0

    total = 0
    for kind in ("pe", "pb"):
        metric = DANJUAN_METRIC.get((asset_type, kind))
        if not metric:
            continue
        series, err = fetch_danjuan_history(index_code, kind=kind)
        if err:
            logger.warning(f"{asset_type} {kind} 历史获取失败: {err}")
            if err == "cookie_expired":
                _set_danjuan_status(False, "Cookie 已过期，请更新蛋卷 Cookie")
            return total
        rows = [
            (asset_type, metric, d, v, f"{index_code} {kind.upper()}历史", "蛋卷基金", None)
            for d, v in series
        ]
        n = bulk_upsert_valuation_metrics(rows)
        total += n
        logger.info(f"{asset_type} {metric} 导入 {n} 条历史（{series[0][0]} ~ {series[-1][0]}）")

    set_setting(flag_key, True)
    _set_danjuan_status(True, "历史数据导入成功")
    return total


def fetch_danjuan_valuation(force=False):
    """
    用蛋卷官方接口获取纳指 + 中证红利今日估值快照，写入数据库。
    指标对齐 valuation_scoring.METRIC_META：
      纳指:   qqq_pe, qqq_peg
      红利:   csi_div_pe, csi_div_pb, csi_div_yield
    首次调用会自动回填10年历史（用于百分位计算）。
    返回 {"nasdaq": {...}, "dividend": {...}} 或 None。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not force and get_setting(f"fetched:danjuan:{today}", False):
        logger.info(f"蛋卷估值 今日({today})已获取，跳过")
        return None

    # 1) 首次回填历史
    for asset, code in DANJUAN_INDEX.items():
        import_danjuan_history(asset, code)

    results = {}
    any_ok = False
    cookie_expired = False

    # 2) 纳指快照
    nd, err = fetch_danjuan_detail(DANJUAN_INDEX["nasdaq"])
    if err:
        logger.warning(f"纳指蛋卷快照失败: {err}")
        if err == "cookie_expired":
            cookie_expired = True
    elif nd:
        rows = []
        if nd["pe"] is not None:
            rows.append(("nasdaq", "qqq_pe", today, nd["pe"], "纳指100市盈率(蛋卷官方)", "蛋卷基金", None))
        if nd["peg"] is not None:
            rows.append(("nasdaq", "qqq_peg", today, nd["peg"], "纳指100 PEG(蛋卷官方)", "蛋卷基金", None))
        if rows:
            bulk_upsert_valuation_metrics(rows)
            any_ok = True
            results["nasdaq"] = nd
            logger.info(f"纳指写入: PE={nd['pe']} PEG={nd['peg']} (官方PE分位={nd['pe_percentile']})")

    # 3) 中证红利快照
    dv, err = fetch_danjuan_detail(DANJUAN_INDEX["dividend"])
    if err:
        logger.warning(f"中证红利蛋卷快照失败: {err}")
        if err == "cookie_expired":
            cookie_expired = True
    elif dv:
        rows = []
        if dv["pe"] is not None:
            rows.append(("dividend", "csi_div_pe", today, dv["pe"], "中证红利市盈率(蛋卷官方)", "蛋卷基金", None))
        if dv["pb"] is not None:
            rows.append(("dividend", "csi_div_pb", today, dv["pb"], "中证红利市净率(蛋卷官方)", "蛋卷基金", None))
        if dv["dividend_yield"] is not None:
            rows.append(("dividend", "csi_div_yield", today, dv["dividend_yield"], "中证红利股息率%(蛋卷官方)", "蛋卷基金", None))
        # V6: 新增ROE保存（蛋卷返回小数0.0965=9.65%，转换为百分比存储）
        if dv["roe"] is not None:
            roe_pct = round(dv["roe"] * 100, 2)
            rows.append(("dividend", "csi_div_roe", today, roe_pct, "中证红利ROE(蛋卷官方)", "蛋卷基金", None))
        if rows:
            bulk_upsert_valuation_metrics(rows)
            any_ok = True
            results["dividend"] = dv
            logger.info(f"中证红利写入: PE={dv['pe']} PB={dv['pb']} 股息率={dv['dividend_yield']:.2f}% ROE={dv.get('roe')}%")

    if cookie_expired:
        _set_danjuan_status(False, "Cookie 已过期，请在「估值分析」页面更新蛋卷 Cookie")
    elif any_ok:
        _set_danjuan_status(True, "数据获取成功")
        set_setting(f"fetched:danjuan:{today}", True)

    return results or None


# ==================================================================
# Layer 2：FRED 宏观数据（利率、VIX、货币、Buffett指标、黄金）
# ==================================================================

def _fetch_fred_series(series_id, observation_start=None, limit=1):
    api_key = get_api_key("fred")
    if not api_key:
        return []

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": max(limit, 1),
    }
    if observation_start:
        params["observation_start"] = observation_start

    try:
        data = _http_get_json(FRED_BASE, params=params)
        obs = data.get("observations", [])
        results = []
        for item in obs:
            v = item.get("value")
            d = item.get("date")
            if not d or v is None or v == "." or v == "":
                continue
            try:
                results.append((d, float(v)))
            except ValueError:
                continue
        return results
    except Exception as e:
        logger.exception(f"FRED {series_id} 获取失败: {e}")
        return []


def fetch_fred_metrics(history_days=15):
    """
    批量获取 FRED 所有关键指标，并计算派生指标（金银比、Buffett、M2同比等）。
    添加异常处理：抓取失败时返回 None，让系统使用缓存或基础分
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=history_days)).strftime("%Y-%m-%d")

        all_raw_rows = []
        series_values = {}

        for series_id, meta in FRED_SERIES.items():
            # CPI是月度数据，需要至少13个月历史才能算同比
            if series_id == "CPIAUCSL":
                cpi_start = (datetime.now() - timedelta(days=450)).strftime("%Y-%m-%d")
                vals = _fetch_fred_series(series_id, observation_start=cpi_start, limit=15)
            else:
                vals = _fetch_fred_series(series_id, observation_start=start, limit=history_days)
            if not vals:
                continue
            series_values[series_id] = vals
            for d, v in vals:
                all_raw_rows.append((
                    meta["asset"], meta["metric"], d, v,
                    meta["label"], "FRED", None
                ))

        if all_raw_rows:
            bulk_upsert_valuation_metrics(all_raw_rows)
            logger.info(f"FRED 原始数据写入: {len(all_raw_rows)} 条")

        # 派生1：金银比 = GOLD / SILVER（注意：金银权重可能不在 FRED_SERIES 里，因为我们用商品价格）
        # 由于我们的数据源不是 FRED 的黄金白银（FMP 的 GCUSD 价格免费可用），这里暂不计算，
        # 黄金相关估值由 valuation_scoring.py 中的独立逻辑处理。

        # 派生2：Buffett Indicator 已停用
        # 原使用 WILL5000PRFC / GDP，但 WILL5000PRFC 当前在FRED返回400，且系统核心评分不依赖该指标。

        # 派生3：CPI同比（需要至少13个月数据）
        cpi_vals = series_values.get("CPIAUCSL", [])
        if len(cpi_vals) >= 2:
            # CPI是月度数据，计算最新值的同比
            cpi_latest_val = cpi_vals[0][1]
            cpi_latest_date = cpi_vals[0][0]
            # 找约12个月前的数据（CPI月度，12个月前应该在列表中）
            cpi_yoy = None
            if len(cpi_vals) >= 13:
                cpi_year_ago_val = cpi_vals[12][1]
                if cpi_year_ago_val > 0:
                    cpi_yoy = round((cpi_latest_val / cpi_year_ago_val - 1) * 100, 2)
            elif len(cpi_vals) >= 2:
                # 数据不足13个月，用最早可用数据近似
                cpi_earliest_val = cpi_vals[-1][1]
                months_diff = len(cpi_vals) - 1
                if cpi_earliest_val > 0 and months_diff > 0:
                    # 年化处理
                    cpi_yoy = round((cpi_latest_val / cpi_earliest_val - 1) * (12.0 / months_diff) * 100, 2)
            if cpi_yoy is not None:
                from services.database import upsert_valuation_metric
                upsert_valuation_metric(
                    "macro", "cpi_yoy", cpi_latest_date, cpi_yoy,
                    f"CPI同比(CPI={cpi_latest_val}, 同比={cpi_yoy}%)", "FRED派生", None
                )
                logger.info(f"CPI同比计算: {cpi_yoy}% (CPI={cpi_latest_val}@{cpi_latest_date})")

        return True

    except Exception as e:
        logger.error(f"FRED宏观数据获取失败: {e}")
        # 不抛出异常，让系统使用缓存或基础分
        return None


def fetch_gold_price_from_fmp(force=False):
    """
    黄金/白银价格：用 FMP 的 GCUSD/SIUSD（免费）作为黄金资产估值的输入。
    作为 FRED 金银价格的 fallback 数据源（FRED GOLDAMGBD228NLBM 数据有时延迟）。
    """
    api_key = get_api_key("fmp")
    today = datetime.now().strftime("%Y-%m-%d")

    if not force:
        cache_key = f"fetched:gold:{today}"
        if get_setting(cache_key, False):
            return None

    if not api_key:
        return None

    try:
        rows = []
        for sym, metric, label in [
            ("GCUSD", "gold_price",   "黄金价格(FMP GCUSD, $/盎司)"),
            ("SIUSD", "silver_price", "白银价格(FMP SIUSD, $/盎司)"),
        ]:
            try:
                data = _http_get_json(f"{FMP_BASE}/quote", params={"symbol": sym, "apikey": api_key})
            except Exception as e:
                logger.warning(f"FMP {sym} quote 失败: {e}")
                continue
            time.sleep(0.3)
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                price = item.get("price")
                date = item.get("timestamp")
                if price:
                    try:
                        date_str = datetime.fromtimestamp(int(date)).strftime("%Y-%m-%d") if date else today
                    except Exception:
                        date_str = today
                    rows.append(("gold", metric, date_str, float(price), label, "FMP", None))

        # 计算金银比
        gold_row = next((r for r in rows if r[1] == "gold_price"), None)
        silver_row = next((r for r in rows if r[1] == "silver_price"), None)
        if gold_row and silver_row and silver_row[3] > 0:
            ratio = round(gold_row[3] / silver_row[3], 4)
            rows.append(("gold", "gold_silver_ratio", gold_row[2], ratio,
                         f"金银比(GCUSD/SIUSD)", "FMP派生", None))

        # 计算 Gold/PPI 比值
        if gold_row:
            try:
                from services.database import get_latest_valuation
                commodity = get_latest_valuation("macro", "commodity_index")
                if commodity and commodity.get("value"):
                    commodity_val = float(commodity["value"])
                    if commodity_val > 0:
                        gold_ppi = round(gold_row[3] / commodity_val * 100, 2)
                        commodity_date = commodity.get("trade_date", gold_row[2])
                        rows.append(("gold", "gold_crb_ratio", commodity_date, gold_ppi,
                                     f"Gold/PPI(Gold={gold_row[3]:.1f}/PPI={commodity_val:.1f})", "FMP+FRED派生", None))
                        logger.info(f"Gold/PPI 比值计算: {gold_ppi:.4f} (Gold={gold_row[3]:.1f}, PPI={commodity_val:.1f})")
            except Exception as e:
                logger.warning(f"Gold/PPI 计算失败: {e}")

        if rows:
            bulk_upsert_valuation_metrics(rows)
            set_setting(f"fetched:gold:{today}", True)
            logger.info(f"黄金/白银价格写入: {len(rows)} 条")
            return {"gold": gold_row[3] if gold_row else None,
                    "silver": silver_row[3] if silver_row else None}
        return None
    except Exception as e:
        logger.exception(f"黄金价格获取失败: {e}")
        return None


# ==================================================================
# Layer 2c: 中国国债收益率（用于红利Dividend Spread）
# ==================================================================

def fetch_china_bond_10y():
    """
    获取中国10年期国债收益率（AkShare）。
    用于计算红利Dividend Spread = 股息率 - 国债收益率。
    返回最新值或None。
    """
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is None or df.empty:
            return None
        # 取最新一行
        latest = df.iloc[-1]
        date_str = str(latest["日期"])
        yield_10y = float(latest["中国国债收益率10年"])
        if yield_10y > 0:
            # 写入数据库
            from services.database import upsert_valuation_metric
            upsert_valuation_metric(
                "macro", "china_bond_10y", date_str, yield_10y,
                "中国10年期国债收益率(%)", "AkShare", None
            )
            logger.info(f"中国10Y国债收益率: {yield_10y:.3f}% ({date_str})")
            return {"date": date_str, "yield": yield_10y}
        return None
    except Exception as e:
        logger.warning(f"中国10Y国债收益率获取失败: {e}")
        return None


# ==================================================================
# Layer 3：中证红利估值（已迁移到蛋卷官方接口 fetch_danjuan_valuation）
# ==================================================================


# ==================================================================
# 总入口
# ==================================================================

def fetch_all_valuations():
    """执行所有估值数据源抓取。失败不抛出异常。"""
    results = {}
    logger.info("=== 开始获取估值指标 ===")

    # Layer 1+3: 蛋卷官方接口（纳指 PE/PEG + 中证红利 PE/PB/股息率/ROE + 10年历史）
    danjuan = fetch_danjuan_valuation()
    if danjuan:
        results["danjuan"] = danjuan

    # Layer 2: FRED 宏观数据（利率/VIX/美元指数）
    fred = fetch_fred_metrics(history_days=15)
    results["fred"] = fred

    # Layer 2b: FMP 黄金/白银价格（金银比 + 黄金价格）
    gold = fetch_gold_price_from_fmp()
    if gold:
        results["gold"] = gold

    # Layer 2c: 中国10年期国债收益率（用于红利Dividend Spread）
    china_bond = fetch_china_bond_10y()
    if china_bond:
        results["china_bond"] = china_bond

    # V7: 计算中证红利 Dividend Spread（股息率 - max(中国10Y国债, CPI同比)）
    # P1升级：考虑通胀侵蚀，用max(国债, CPI)作为真实机会成本
    try:
        from services.database import get_latest_valuation
        div_yield = get_latest_valuation("dividend", "csi_div_yield")
        bond_yield = get_latest_valuation("macro", "china_bond_10y")
        cpi_yoy = get_latest_valuation("macro", "cpi_yoy")
        if div_yield and bond_yield:
            dy_val = float(div_yield["value"])
            by_val = float(bond_yield["value"])
            # V7: 使用max(国债, CPI同比)作为机会成本
            cpi_val = float(cpi_yoy["value"]) if cpi_yoy else 0.0
            opportunity_cost = max(by_val, cpi_val)
            spread = round(dy_val - opportunity_cost, 2)
            today = datetime.now().strftime("%Y-%m-%d")
            from services.database import upsert_valuation_metric
            upsert_valuation_metric(
                "dividend", "dividend_spread", today, spread,
                f"红利利差(股息率{dy_val:.2f}% - max(国债{by_val:.2f}%,CPI{cpi_val:.2f}%))", "派生计算", None
            )
            logger.info(f"Dividend Spread 计算: {spread:.2f}% (股息率{dy_val:.2f}% - 机会成本{opportunity_cost:.2f}%)")
            results["dividend_spread"] = spread
    except Exception as e:
        logger.warning(f"Dividend Spread 计算失败: {e}")

    logger.info(f"=== 估值指标获取完成: {list(results.keys())} ===")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch_all_valuations()
