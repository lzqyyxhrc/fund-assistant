"""
V4 估值评分系统（长期智能定投引擎）
====================

三层架构：
  Layer 1：成分股加权估值（QQQ Top50，覆盖 90.8%）
  Layer 2：宏观修正因子（加法模式，±15 分漂移）
  Layer 3：跨资产统一评分（纳指 / 中证红利 / 黄金 → 0-100 分）

V4 优化（根据专业反馈重构）：
  1. 纳指：删除PB（PE/PB/PS高度相关重复计分），增加PEG（增长维度）
     配置：PE 70% / PEG 30%
  2. 红利：PE 40% / PB 30% / 股息率 30%，加入PB避免高股息陷阱
  3. 黄金：V4.1修正——金银比正向/利率逆向/金价中枢上调
     配置：金银比 30% / 实际利率 40% / 黄金价格 30%
  4. 删除巴菲特指标（美股市值/GDP与纳指脱钩）
  5. 下调信赖度门槛：<100天 fallback / 100-500天 limited / >500天 full
  6. 保留宏观加法修正，避免乘法导致极端值钝化
  7. VIX非线性阈值触发（>25时介入），避免牛市低波动误判

关键能力：
  1. 历史百分位：当前值在历史中的位置（数据足够时）
  2. 常识区间 fallback：数据不足时用已知区间给参考评分（标注"临时"）
  3. 宏观修正（加法）：利率/VIX/美元对资产估值的加权调整
  4. 跨资产统一评分：三类资产都是 0-100 分，便于横向比较（动态再平衡/轮动）
  5. 买卖区间建议 + 定投倍数建议
  6. 数据可信赖度标记：full / limited / fallback

最终分数解释（0~100，越低越便宜）：
  [0, 20)   极度低估   → 2.0x 加投 / 超配
  [20, 40)  低估        → 1.5x 多投
  [40, 60)  正常        → 1.0x 定投
  [60, 80)  高估        → 0.5x 少投
  [80, 100] 极度高估   → 0.0x 暂停 / 考虑止盈
"""

import logging
from datetime import datetime, timedelta

import pandas as pd

from services.database import get_valuation_history, get_latest_valuation

logger = logging.getLogger(__name__)


# ==================================================================
# 指标元数据 + 常识区间（用于 fallback 评分）
# ==================================================================
# low/mid/high: 该指标的"合理区间"端点，用于数据不足时的临时评分
#   score_map: value -> [0,100] 的分数映射
#   正向指标（越高越贵）：value <= low -> 0, value >= high -> 100, 线性插值
#   逆向指标（越高越便宜）：value <= low -> 100, value >= high -> 0, 线性插值

METRIC_META = {
    # ---- 纳指 (V4+蛋卷数据源: PE历史分位为核心 70% + PEG 30%) ----
    "qqq_pe": {
        "label": "纳指100 市盈率(蛋卷官方)",
        "inverse": False,
        "asset_weight": 0.7,
        "asset": "nasdaq",
        "low": 18.0,       # PE < 18: 极度低估（近10年纳指区间）
        "mid": 28.0,       # PE ~ 28: 正常
        "high": 35.0,      # PE > 35: 极度高估
        "typical_min": 15.0,
        "typical_max": 40.0,
        "note": "蛋卷官方纳指100 PE，10年历史，优先用历史分位",
    },
    "qqq_peg": {
        "label": "纳指100 PEG (PE/Growth, 蛋卷官方)",
        "inverse": False,
        "asset_weight": 0.3,
        "asset": "nasdaq",
        "low": 0.8,        # PEG < 0.8: 极度低估（估值相对于增长很便宜）
        "mid": 1.5,        # PEG ~ 1.5: 正常估值
        "high": 2.5,       # PEG > 2.5: 极度高估
        "typical_min": 0.5,
        "typical_max": 4.0,
        "note": "PEG = PE / EPS 增长率，越低估值相对于增长越便宜",
    },

    # ---- 红利 V6: 三层架构（估值60% + 盈利与安全边际25% + 结构稳定性15%） ----
    # V6 升级：加入ROE盈利锚、Dividend Spread利率锚、PE/PB mismatch结构检测
    # 第1层：估值层
    "csi_div_pe": {
        "label": "中证红利市盈率",
        "inverse": False,
        "asset_weight": 0.30,
        "asset": "dividend",
        "low": 8.0,
        "mid": 12.0,
        "high": 18.0,
        "typical_min": 6.0,
        "typical_max": 25.0,
    },
    "csi_div_pb": {
        "label": "中证红利市净率",
        "inverse": False,
        "asset_weight": 0.20,
        "asset": "dividend",
        "low": 0.8,
        "mid": 1.15,
        "high": 1.5,
        "typical_min": 0.6,
        "typical_max": 2.0,
        "note": "PB反映资产账面价值质量，避免高股息陷阱",
    },
    "csi_div_yield": {
        "label": "中证红利股息率(%)",
        "inverse": True,
        "asset_weight": 0.25,
        "asset": "dividend",
        "low": 5.5,        # 股息率 > 5.5%: 极度低估
        "mid": 4.5,
        "high": 3.0,       # 股息率 < 3%: 贵
        "typical_min": 2.0,
        "typical_max": 8.0,
        "note": "蛋卷无股息率历史接口，每日快照累积，暂用常识区间",
    },
    # V6.1: ROE改为调节因子（不与PE/PB重复计分，仅作为盈利质量校验）
    "csi_div_roe": {
        "label": "中证红利ROE(%)",
        "inverse": True,
        "asset_weight": 0.0,   # 不独立计分，作为调节因子
        "asset": "dividend",
        "adjustment": True,    # 标记为调节因子
        "low": 15.0,
        "mid": 10.0,
        "high": 5.0,
        "typical_min": 2.0,
        "typical_max": 20.0,
        "note": "ROE调节因子：低ROE(>70分)时整体评分+12，高ROE(<30分)时-8，避免与PE/PB重复",
    },
    # V6.1: Dividend Spread阈值调平滑，权重提升
    "dividend_spread": {
        "label": "红利利差(股息率-国债%)",
        "inverse": True,
        "asset_weight": 0.25,
        "asset": "dividend",
        "low": 4.0,        # Spread > 4%: 极便宜
        "mid": 2.0,        # Spread ~ 2%: 正常
        "high": -1.0,      # Spread < -1%: 极贵
        "typical_min": -2.0,
        "typical_max": 6.0,
        "note": "红利核心指标：股息率减中国10Y国债收益率，3-5%=便宜，>5%=极便宜",
    },
    # V6.1: 结构稳定性改为penalty（不独立计分，仅作为风险扣减）

    # ---- 黄金 (V5: 实际利率 50% / Gold/PPI 30% / 金银比 20%) ----
    # V5 升级：全部改为历史百分位法，与纳指/红利体系保持一致
    # 删除绝对金价（美元购买力变化导致直接比较无意义）
    # 新增 Gold/PPI（黄金相对美国生产者价格指数，衡量相对实物资产价值）
    "real_rate_10y": {
        "label": "10年TIPS实际利率(%)",
        "inverse": False,  # 正向：利率越高 → 黄金估值压力越大 → 评分越高（少投）
        "asset_weight": 0.5,
        "asset": "gold",
        "data_asset": "macro",  # 实际数据存储在 macro 下
        "low": -1.0,       # fallback 区间
        "mid": 1.0,
        "high": 3.0,
        "typical_min": -2.0,
        "typical_max": 4.0,
        "note": "历史百分位法：利率处于历史高位→黄金贵(高分)→少投",
    },
    "gold_crb_ratio": {
        "label": "黄金实际价格(Gold/PPI×100)",
        "inverse": False,  # 正向：比值越高 → 黄金实际价格越贵 → 评分越高（少投）
        "asset_weight": 0.3,
        "asset": "gold",
        "low": 800,        # fallback 区间（Gold/PPI×100历史约700-2000）
        "mid": 1200,
        "high": 1800,
        "typical_min": 500,
        "typical_max": 2500,
        "note": "黄金实际价格 = 金价/PPIACO×100，通胀调整后的真实购买力价格（月频）",
    },
    "gold_silver_ratio": {
        "label": "金银比",
        "inverse": True,   # 逆向：比值越高 → 黄金相对白银越便宜 → 评分越低（多投）
        "asset_weight": 0.2,
        "asset": "gold",
        "low": 120.0,      # fallback 区间（历史约30-120）
        "mid": 70.0,
        "high": 30.0,
        "typical_min": 20.0,
        "typical_max": 130.0,
        "note": "历史百分位法：比值处于历史高位→黄金相对白银便宜(低分)→多投",
    },
}


# ==================================================================
# 宏观指标元数据（用于宏观修正因子，V3: 精简同质化指标）
# ==================================================================
MACRO_META = {
    "treasury_10y": {
        "label": "10年期美国国债收益率(%)",
        "asset": "macro",
        "low": 2.0,
        "mid": 4.0,
        "high": 6.0,
        "impact_on": {
            "nasdaq": {"direction": -1, "weight": 0.6},   # 利率↑ → 纳指估值承压
            # V4.1 移除对黄金的重复影响：TIPS实际利率已在核心指标中覆盖
            # 保留对纳指的影响（无重复）
        },
        "note": "作为大环境流动性的终极定价锚（仅修正纳指，避免与TIPS重复）",
    },
    "vix": {
        "label": "VIX 波动率指数",
        "asset": "macro",
        "low": 12.0,
        "mid": 20.0,
        "high": 35.0,
        "threshold": 25.0,  # 非线性阈值：仅当VIX突破25时作为"黄金坑加分项"介入
        "impact_on": {
            "nasdaq": {"direction": 1, "weight": 0.4},    # VIX↑ → 恐慌 → 短期机会（低估信号）
        },
        "note": "市场恐慌情绪指标，高VIX是逆向买入信号（非线性阈值触发）",
    },
    "dollar_index": {
        "label": "美元贸易加权指数",
        "asset": "macro",
        "low": 95.0,
        "mid": 103.0,
        "high": 112.0,
        "impact_on": {
            "gold":   {"direction": 1, "weight": 0.5},    # 美元强 → 黄金以美元计价相对便宜
        },
        "note": "美元走势影响黄金相对价值",
    },
    # 注释：联邦基金利率已移除，因其与10年国债收益率高度正相关，
    # 重复计入会导致"利率因素"在纳指上被双重放大
}


# ==================================================================
# 基础工具：百分位计算 + 常识区间评分
# ==================================================================

def _calc_percentile(history_rows, window_years=None):
    """
    计算当前值在历史中的百分位。
    返回: (current_value, percentile, data_points_count, mean, min, max)
    """
    if not history_rows:
        return None, None, 0, None, None, None

    df = pd.DataFrame(history_rows)
    df["date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("date").dropna(subset=["value"])
    if df.empty:
        return None, None, 0, None, None, None

    if window_years:
        cutoff = df["date"].max() - pd.Timedelta(days=window_years * 365)
        df_window = df[df["date"] >= cutoff]
        if len(df_window) < 30:
            df_window = df
    else:
        df_window = df

    current = float(df["value"].iloc[-1])
    values = df_window["value"].values

    below = (values <= current).sum()
    pct = below / len(values) if len(values) > 0 else 0.5

    return (
        current,
        float(pct),
        int(len(values)),
        float(df_window["value"].mean()),
        float(df_window["value"].min()),
        float(df_window["value"].max()),
    )


def _score_from_interval(value, low, mid, high, inverse=False):
    """
    用常识区间映射出 0-100 的参考评分。
    线性插值：
      正向: value=low→0, value=mid→50, value=high→100
      逆向: value=low→100, value=mid→50, value=high→0
    """
    if value is None:
        return None

    if not inverse:
        if value <= low:
            return 0.0
        if value >= high:
            return 100.0
        if value <= mid:
            return (value - low) / (mid - low) * 50.0
        return 50.0 + (value - mid) / (high - mid) * 50.0
    else:
        # 逆向：value >= low（高值）→ 0分（便宜），value <= high（低值）→ 100分（贵）
        # 注意：逆向时 low > high（例如股息率 low=5.5, high=3.0）
        if value >= low:
            return 0.0
        if value <= high:
            return 100.0
        if value >= mid:
            return (low - value) / (low - mid) * 50.0
        return 50.0 + (mid - value) / (mid - high) * 50.0


# ==================================================================
# 单个指标评分（优先百分位，回退常识区间）
# ==================================================================

def score_metric(asset_type, metric_name, window_years=None):
    """
    对某个单一指标计算：当前值、评分(0-100)。
    策略（V4: 调整信赖度阈值）：
      1. 有 > 500 天历史数据（约2年） → 用百分位（信赖度：full）
      2. 有 100-500 天历史 → 用百分位 + 标记（信赖度：limited）
      3. < 100 天或无历史 → 用常识区间评分（信赖度：fallback，临时参考）
    """
    meta = METRIC_META.get(metric_name)
    if not meta:
        return None

    # 使用 data_asset（实际数据存储位置）或 asset_type（逻辑归属）查询数据
    query_asset = meta.get("data_asset", asset_type)

    # --- 阶段 1：尝试百分位 ---
    history = get_valuation_history(query_asset, metric_name)
    current, pct, n, mean, mn, mx = _calc_percentile(history, window_years=window_years)

    # 数据日期（最新一条记录的 trade_date）
    data_date = max((r["trade_date"] for r in history), default=None) if history else None

    base = {
        "metric_name": metric_name,
        "label": meta["label"],
        "current": current,
        "data_date": data_date,
        "data_points": n,
        "inverse": meta["inverse"],
        "typical_range": (meta.get("typical_min"), meta.get("typical_max")),
    }

    # 当前值缺失 → 完全无法评分
    if current is None:
        # 尝试直接读 latest 记录（历史表为空但有今日数据）
        latest = get_latest_valuation(query_asset, metric_name)
        if latest:
            current = float(latest["value"])
            base["current"] = current
            base["data_date"] = latest.get("trade_date")
        else:
            base.update({"score": None, "percentile": None, "reliability": "no_data"})
            return base

    # --- 阶段 2：决定用百分位还是常识区间 ---
    if n > 500:
        # 百分位（可信赖，超过2年数据）
        score = (1.0 - pct) * 100.0 if meta["inverse"] else pct * 100.0
        base.update({
            "score": round(score, 1),
            "percentile": round(pct * 100, 1),
            "mean": round(mean, 3) if mean else None,
            "min": round(mn, 3) if mn else None,
            "max": round(mx, 3) if mx else None,
            "reliability": "full",
            "method": "percentile",
            "note": f"历史数据{n}天（{n/252:.1f}年），可信度高",
        })
    elif n >= 100:
        # 百分位有限（数据偏少，但超过100天）
        score = (1.0 - pct) * 100.0 if meta["inverse"] else pct * 100.0
        base.update({
            "score": round(score, 1),
            "percentile": round(pct * 100, 1),
            "mean": round(mean, 3) if mean else None,
            "min": round(mn, 3) if mn else None,
            "max": round(mx, 3) if mx else None,
            "reliability": "limited",
            "method": "percentile_limited",
            "note": f"历史数据{n}天（{n/252:.1f}年），建议积累至2年后完全信赖",
        })
    else:
        # fallback：常识区间
        score = _score_from_interval(current, meta.get("low"), meta.get("mid"), meta.get("high"), meta["inverse"])
        base.update({
            "score": round(score, 1) if score is not None else None,
            "percentile": None,
            "reliability": "fallback",
            "method": "interval_fallback",
            "note": f"历史数据仅{n}天（{n/252:.2f}年），强制使用常识区间估算（仅供参考）",
        })

    return base


# ==================================================================
# 宏观修正因子（V3: 改为加法，避免乘法导致极端值钝化）
# ==================================================================

def _get_macro_factor(target_asset):
    """
    计算宏观修正偏移量（加法模式）：
      - 收集 MACRO_META 中所有影响 target_asset 的指标
      - 每一项给出一个 ±15 的分数偏移
      - 最终汇总：-15 ~ +15（限制在 ±15 之间）
      - VIX采用非线性阈值触发：仅当VIX > 25时作为"黄金坑加分项"介入
    返回: (offset, detail_list)
    """
    try:
        details = []
        total_weight = 0.0
        weighted_offset = 0.0

        for metric_key, meta in MACRO_META.items():
            impact = meta["impact_on"].get(target_asset)
            if not impact:
                continue

            latest = get_latest_valuation(meta["asset"], metric_key)
            if not latest:
                continue

            try:
                value = float(latest["value"])
            except Exception:
                continue

            # VIX非线性阈值触发：仅当VIX突破阈值时才参与修正
            if metric_key == "vix":
                threshold = meta.get("threshold", 25.0)
                if value < threshold:
                    # VIX低于阈值，保持中性，不参与修正
                    continue

            # 对宏观指标本身做"相对位置"评估（0-100）
            # 低 = 0分, 高 = 100分（不区分方向，方向在 impact 里）
            pos_score = _score_from_interval(value, meta["low"], meta["mid"], meta["high"], inverse=False)
            if pos_score is None:
                continue

            # pos_score=50 为中性 → 偏离50的程度代表"压力强度"
            deviation = (pos_score - 50.0) / 50.0   # -1 ~ +1

            # 计算对评分的影响：
            #   direction=-1（利率↑ → 股票↓ → 当前股票相对更便宜 → 降低评分）
            #   direction=+1（VIX↑ → 恐慌 → 机会 → 降低评分）
            # 统一为：adjust_sign = -1 * direction
            # deviation × (-direction) = 正值 → 应提高分数（更贵），负值 → 降低分数（更便宜）

            adjust_impact = deviation * impact["direction"] * -1  # 统一符号
            weighted_offset += adjust_impact * impact["weight"] * 15  # 最大 ±15
            total_weight += impact["weight"]

            # 记录明细（用于 UI 展示）
            pressure_desc = "偏高" if pos_score > 65 else "偏低" if pos_score < 35 else "中性"
            details.append({
                "metric": metric_key,
                "label": meta["label"],
                "value": round(value, 3),
                "data_date": latest.get("trade_date"),
                "pressure_score": round(pos_score, 1),
                "pressure": pressure_desc,
                "weight": impact["weight"],
                "direction": impact["direction"],
            })

        if total_weight == 0:
            return 0.0, []

        avg_offset = weighted_offset / total_weight  # -15 ~ +15
        # 限制在 ±15 之间
        offset = max(-15.0, min(15.0, avg_offset))

        return round(offset, 1), details

    except Exception as e:
        logger.error(f"宏观指标计算失败: {e}")
        # 宏观指标异常时，返回0偏移量，并标记状态
        return 0.0, [{"metric": "system", "label": "宏观指标异常", "value": None, "pressure": "数据缺失", "note": "使用基础分"}]


# ==================================================================
# 大类资产综合评分（V3: 宏观修正改为加法）
# ==================================================================

def score_asset(asset_type, window_years=None, apply_macro=True):
    """
    返回该资产的综合评分：
      base_score = Σ(indicator_score × weight)
      final_score = base_score + macro_offset（限幅在 0-100）
    """
    metrics_for_asset = [
        k for k, v in METRIC_META.items() if v["asset"] == asset_type
    ]

    scored = []
    total_weight = 0.0
    weighted_score = 0.0

    # 金银比权重动态调整：极端区间(<40或>100)权重减半
    weight_adjustments = {}
    for m in metrics_for_asset:
        if m == "gold_silver_ratio":
            s_temp = score_metric(asset_type, m, window_years=window_years)
            if s_temp and s_temp.get("current") is not None:
                gsr_val = float(s_temp["current"])
                if gsr_val < 40 or gsr_val > 100:
                    weight_adjustments[m] = 0.5  # 权重减半

    # V6.1: 分离调节因子和主评分指标
    main_scored = []
    adjustment_items = []

    for m in metrics_for_asset:
        s = score_metric(asset_type, m, window_years=window_years)
        if not s:
            continue
        meta = METRIC_META[m]
        optional = meta.get("optional")

        if s["score"] is None:
            if optional:
                continue
            continue

        # 调节因子（asset_weight=0 或 adjustment=True）：不计入主权重
        if meta.get("asset_weight", 0) == 0 or meta.get("adjustment"):
            adjustment_items.append((m, s, meta))
            scored.append(s)
            continue

        w = meta["asset_weight"] * weight_adjustments.get(m, 1.0)
        weighted_score += s["score"] * w
        total_weight += w
        scored.append(s)
        main_scored.append(s)

    base_score = weighted_score / total_weight if total_weight > 0 else 50.0

    # V6.1: 红利资产调节因子处理
    adjustments = []
    if asset_type == "dividend":
        # 1) ROE稳定性因子（V7 P1升级）：历史ROE标准差越大→盈利越不稳定→风险越高→加分（贵/少投）
        roe_history = get_valuation_history("dividend", "csi_div_roe")
        roe_stability_applied = False
        if roe_history and len(roe_history) >= 30:
            import statistics
            roe_vals = [float(r["value"]) for r in roe_history if r.get("value") is not None]
            if len(roe_vals) >= 30:
                roe_mean = statistics.mean(roe_vals)
                roe_std = statistics.stdev(roe_vals) if len(roe_vals) > 1 else 0
                # 标准差越大 → 盈利波动越大 → 风险越高 → 加分
                # 参考：ROE标准差<1%为稳定，>3%为极不稳定
                if roe_std > 3.0:
                    adj = +10
                    adjustments.append(("ROE稳定性", adj, f"ROE标准差{roe_std:.1f}%极高，盈利极不稳定，+{adj}"))
                    roe_stability_applied = True
                elif roe_std > 1.5:
                    adj = +5
                    adjustments.append(("ROE稳定性", adj, f"ROE标准差{roe_std:.1f}%偏高，盈利波动大，+{adj}"))
                    roe_stability_applied = True
                scored.append({
                    "metric_name": "roe_stability",
                    "label": "ROE稳定性(历史标准差)",
                    "current": round(roe_std, 2),
                    "score": None,
                    "reliability": "derived",
                    "method": "roe_std",
                    "note": f"ROE均值{roe_mean:.1f}% 标准差{roe_std:.1f}% (数据{len(roe_vals)}天)",
                })

        # 1b) ROE值调节（fallback）：当稳定性数据不足时，用当前ROE值调节
        if not roe_stability_applied:
            roe_item = next((x for x in scored if x.get("metric_name") == "csi_div_roe"), None)
            if roe_item and roe_item.get("score") is not None:
                roe_score = roe_item["score"]
                if roe_score > 70:  # ROE极低（盈利弱）
                    adj = +12
                    adjustments.append(("ROE调节", adj, f"ROE评分{roe_score:.0f}>70，盈利弱，整体评分+{adj}"))
                elif roe_score < 30:  # ROE极高（盈利强）
                    adj = -8
                    adjustments.append(("ROE调节", adj, f"ROE评分{roe_score:.0f}<30，盈利强，整体评分{adj}"))

        # 2) 结构稳定性penalty：PE/PB mismatch作为风险扣减（不独立计分）
        pe_item = next((x for x in scored if x.get("metric_name") == "csi_div_pe"), None)
        pb_item = next((x for x in scored if x.get("metric_name") == "csi_div_pb"), None)
        if pe_item and pb_item:
            pe_pct = pe_item.get("percentile")
            pb_pct = pb_item.get("percentile")
            if pe_pct is not None and pb_pct is not None:
                mismatch = pe_pct - pb_pct
                penalty = 0
                if mismatch > 30:
                    penalty = +8
                elif mismatch > 20:
                    penalty = +4
                if penalty > 0:
                    adjustments.append(("结构风险", penalty, f"PE-PB mismatch={mismatch:.0f}>20，盈利恶化风险，+{penalty}"))
                # 记录mismatch信息（仅展示，不计分）
                scored.append({
                    "metric_name": "structure_stability",
                    "label": "结构稳定性(PE/PB mismatch)",
                    "current": round(mismatch, 1),
                    "score": None,  # 不独立评分
                    "percentile": None,
                    "reliability": "derived",
                    "method": "pe_pb_mismatch",
                    "note": f"PE百分位{pe_pct:.0f}% - PB百分位{pb_pct:.0f}% = {mismatch:.0f} (仅作为风险参考，已计入penalty)",
                })

    # 应用调节
    for _, adj, note in adjustments:
        base_score += adj

    if total_weight == 0:
        return {
            "asset_type": asset_type,
            "base_score": None,
            "score": None,
            "macro_offset": None,
            "metrics": scored,
            "macro_details": [],
            "recommendation": "暂无数据",
            "band": "无数据",
            "invest_multiplier": 0.0,
        }

    # 宏观修正（加法模式）
    macro_offset = 0.0
    macro_details = []
    if apply_macro:
        macro_offset, macro_details = _get_macro_factor(asset_type)

    final_score = base_score + macro_offset
    final_score = max(0.0, min(100.0, final_score))

    return {
        "asset_type": asset_type,
        "base_score": round(base_score, 1),
        "score": round(final_score, 1),
        "macro_offset": macro_offset,
        "metrics": scored,
        "macro_details": macro_details,
        "recommendation": _recommend(final_score),
        "band": _band(final_score),
        "invest_multiplier": _multiplier(final_score),
    }


def _band(score):
    if score < 20: return "极低估"
    if score < 40: return "低估"
    if score < 60: return "正常"
    if score < 80: return "高估"
    return "极高估"


def _recommend(score):
    if score < 20: return "极低估，建议超配 / 加投 2.0x"
    if score < 40: return "低估，建议多投 1.5x"
    if score < 60: return "正常估值，按计划定投 1.0x"
    if score < 80: return "高估，建议少投 0.7x"
    return "极高估，建议少投 / 谨慎持有 0.3x"


def _multiplier(score):
    if score < 20: return 2.0
    if score < 40: return 1.5
    if score < 60: return 1.0
    if score < 80: return 0.7
    return 0.3


# ==================================================================
# 总入口：三大资产估值全景
# ==================================================================

ASSET_LABELS = {
    "nasdaq":   "纳斯达克科技",
    "dividend": "中证红利",
    "gold":     "黄金",
}


def get_valuation_overview(window_years=None, apply_macro=True):
    """
    返回三大资产的整体估值情况，用于 dashboard 展示。
    输出格式：
      {
        "assets": { "nasdaq": {...}, "dividend": {...}, "gold": {...} },
        "ranking": [("nasdaq", 15.3), ("gold", 42.1), ("dividend", 78.0)],  # 按分数升序（便宜在前）
        "generated_at": "2026-06-11 14:30:12",
      }
    """
    assets = {
        at: score_asset(at, window_years=window_years, apply_macro=apply_macro)
        for at in ["nasdaq", "dividend", "gold"]
    }

    # 可用于配置的资产排名（分数越低越便宜，越推荐配置）
    ranking = []
    for at, data in assets.items():
        if data["score"] is not None:
            ranking.append((at, data["score"]))
    ranking.sort(key=lambda x: x[1])   # 便宜 → 贵

    return {
        "assets": assets,
        "ranking": ranking,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_years": window_years or "全部历史",
        "macro_enabled": apply_macro,
    }


# ==================================================================
# 智能定投倍数建议（外部接口）
# ==================================================================

def get_auto_invest_multiplier(asset_type, base=1.0, window_years=None):
    """
    根据估值给出定投倍数。
    返回: (multiplier, asset_score_detail)
    """
    overview = score_asset(asset_type, window_years=window_years)
    score = overview["score"]
    if score is None:
        return base, overview
    return base * _multiplier(score), overview


def get_portfolio_suggestion(base_amount=1000.0, window_years=None):
    """
    基于三类资产的估值差给出一个简单的组合建议。
    返回：[{asset, label, score, amount, ratio, multiplier}, ...]
    """
    overview = get_valuation_overview(window_years=window_years)

    valid = []
    for at in ["nasdaq", "dividend", "gold"]:
        d = overview["assets"][at]
        if d["score"] is not None:
            valid.append((at, d))

    if not valid:
        return []

    # 核心：以 "score 越低，权重越高" 为原则
    # 反转分数作为权重分数（越便宜 → 越高）
    def weight_of(s):
        return max(100.0 - s, 5.0)   # 最低保留 5%，避免完全排除

    weights = [(at, weight_of(d["score"]), d) for at, d in valid]
    total_w = sum(w for _, w, _ in weights)

    result = []
    for at, w, d in weights:
        ratio = w / total_w
        amount = base_amount * ratio
        result.append({
            "asset": at,
            "label": ASSET_LABELS.get(at, at),
            "score": d["score"],
            "band": d["band"],
            "amount": round(amount, 2),
            "ratio": round(ratio * 100, 1),
            "multiplier": d["invest_multiplier"],
            "recommendation": d["recommendation"],
        })
    result.sort(key=lambda x: x["score"])  # 便宜在前
    return result


# ==================================================================
# V7: 宏观状态层 + 统一利率锚 + 资金分配引擎
# ==================================================================

# 宏观状态 → 资产权重调整映射
REGIME_WEIGHT_ADJUST = {
    "Risk-On":            {"nasdaq": +10, "dividend": -10, "gold": -10},
    "Risk-Off":           {"nasdaq": -15, "dividend": +10, "gold": +15},
    "Stagflation":        {"nasdaq": -10, "dividend": +10, "gold": +20},
    "Liquidity Expansion": {"nasdaq": +15, "dividend": 0,   "gold": -15},
    "Neutral":            {"nasdaq": 0,   "dividend": 0,   "gold": 0},
}


def detect_macro_regime():
    """
    V7 宏观状态判断：基于实际利率、VIX、商品趋势判断当前宏观环境。
    返回: {"regime": str, "signals": dict, "adjustments": dict}
    """
    signals = {}

    # 1. 实际利率
    latest = get_latest_valuation("macro", "real_rate_10y")
    real_yield = float(latest["value"]) if latest else None
    signals["real_yield"] = round(real_yield, 2) if real_yield else None

    # 2. VIX
    latest = get_latest_valuation("macro", "vix")
    vix = float(latest["value"]) if latest else None
    signals["vix"] = round(vix, 1) if vix else None

    # 3. 美元指数
    latest = get_latest_valuation("macro", "dollar_index")
    dxy = float(latest["value"]) if latest else None
    signals["dxy"] = round(dxy, 1) if dxy else None

    # 4. 商品指数（PPI作为代理）
    latest = get_latest_valuation("macro", "commodity_index")
    commodity = float(latest["value"]) if latest else None
    signals["commodity"] = round(commodity, 1) if commodity else None

    # 状态判断（优先级从高到低）
    regime = "Neutral"
    reasons = []

    if real_yield is not None and vix is not None:
        if real_yield > 2.0 and vix > 20:
            regime = "Risk-Off"
            reasons.append(f"实际利率{real_yield:.1f}%高且VIX{vix:.0f}恐慌")
        elif real_yield > 1.5 and vix < 18:
            regime = "Risk-On"
            reasons.append(f"实际利率{real_yield:.1f}%偏高但VIX{vix:.0f}低波动")

    if regime == "Neutral" and real_yield is not None and commodity is not None:
        if real_yield > 0 and commodity > 280:
            regime = "Stagflation"
            reasons.append(f"实际利率{real_yield:.1f}%为正且商品PPI{commodity:.0f}高位")

    # 默认说明
    if not reasons:
        reasons.append("无极端信号，处于中性状态")

    adjustments = REGIME_WEIGHT_ADJUST.get(regime, REGIME_WEIGHT_ADJUST["Neutral"])

    return {
        "regime": regime,
        "regime_cn": _regime_cn(regime),
        "reasons": reasons,
        "signals": signals,
        "adjustments": adjustments,
    }


def _regime_cn(regime):
    return {
        "Risk-On": "风险偏好",
        "Risk-Off": "风险规避",
        "Stagflation": "滞胀",
        "Liquidity Expansion": "流动性扩张",
        "Neutral": "中性",
    }.get(regime, regime)


def get_global_rate_anchor():
    """
    V7 统一利率锚：70%美国实际利率 + 30%中国10Y国债。
    返回: {"rate": float, "components": dict}
    """
    us_real = None
    cn_10y = None

    latest = get_latest_valuation("macro", "real_rate_10y")
    if latest:
        us_real = float(latest["value"])

    latest = get_latest_valuation("macro", "china_bond_10y")
    if latest:
        cn_10y = float(latest["value"])

    if us_real is not None and cn_10y is not None:
        global_rate = round(0.7 * us_real + 0.3 * cn_10y, 2)
    elif us_real is not None:
        global_rate = round(us_real, 2)
    elif cn_10y is not None:
        global_rate = round(cn_10y, 2)
    else:
        global_rate = None

    return {
        "rate": global_rate,
        "components": {
            "us_real_yield": us_real,
            "cn_10y": cn_10y,
        },
        "formula": "Global Rate = 0.7 * US Real Yield + 0.3 * CN 10Y",
    }


# ==================================================================
# V7: 资金分配引擎（Capital Allocation Engine）
# ==================================================================

def allocate_capital_v7(base_amount=1000.0, window_years=None,
                        min_weight=0.10, max_weight=0.60, temperature=25.0):
    """
    V7 资金分配引擎：基于估值分数 + 宏观状态调整，输出带约束的资产配置权重。

    参数:
        base_amount: 总配置金额
        min_weight: 单资产最小权重（默认10%）
        max_weight: 单资产最大权重（默认60%）
        temperature: softmax温度（越小越集中，越大越均匀）
    """
    # 1. 获取三资产估值
    overview = get_valuation_overview(window_years=window_years)
    assets = overview["assets"]

    # 2. 获取宏观状态
    regime = detect_macro_regime()
    regime_adj = regime["adjustments"]

    # 3. 计算每个资产的"吸引力分数"（分数越低越便宜 → 吸引力越高）
    attractiveness = {}
    for at in ["nasdaq", "dividend", "gold"]:
        d = assets[at]
        if d["score"] is None:
            attractiveness[at] = 0.0
            continue
        # 基础吸引力：100 - 估值分数（便宜→高吸引力）
        base_attr = max(100.0 - d["score"], 1.0)
        # 宏观状态调整
        adj = regime_adj.get(at, 0)
        # 调整后的吸引力（+10%上限，避免过度偏离）
        adjusted_attr = base_attr * (1 + adj / 100.0)
        attractiveness[at] = max(adjusted_attr, 1.0)

    # 4. Softmax 权重分配
    import math
    exp_scores = {k: math.exp(v / temperature) for k, v in attractiveness.items()}
    total_exp = sum(exp_scores.values())
    raw_weights = {k: v / total_exp for k, v in exp_scores.items()}

    # 5. Min/Max 约束（clip and redistribute）
    weights = dict(raw_weights)
    for _ in range(5):  # 最多迭代5次
        # 找出超限的
        over_max = {k: v - max_weight for k, v in weights.items() if v > max_weight}
        under_min = {k: min_weight - v for k, v in weights.items() if v < min_weight}

        if not over_max and not under_min:
            break

        # 先把超限的clip到边界
        for k in over_max:
            weights[k] = max_weight
        for k in under_min:
            weights[k] = min_weight

        # 计算剩余需要分配的权重
        excess = sum(over_max.values()) if over_max else 0
        deficit = sum(under_min.values()) if under_min else 0
        delta = excess - deficit

        # 把delta分配给未超限的资产
        unconstrained = [k for k in weights if k not in over_max and k not in under_min]
        if unconstrained and abs(delta) > 0.001:
            share = delta / len(unconstrained)
            for k in unconstrained:
                weights[k] += share

    # 6. 最终归一化（确保总和=1）
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {k: v / total_w for k, v in weights.items()}

    # 7. 组装结果
    result = []
    for at in ["nasdaq", "dividend", "gold"]:
        d = assets[at]
        w = weights.get(at, 0.0)
        result.append({
            "asset": at,
            "label": ASSET_LABELS.get(at, at),
            "score": d.get("score"),
            "band": d.get("band"),
            "weight": round(w * 100, 1),
            "amount": round(base_amount * w, 2),
            "multiplier": d.get("invest_multiplier", 1.0),
            "attractiveness": round(attractiveness.get(at, 0), 1),
        })

    result.sort(key=lambda x: x["weight"], reverse=True)

    return {
        "regime": regime,
        "global_rate": get_global_rate_anchor(),
        "allocations": result,
        "total_amount": base_amount,
        "constraints": {"min": min_weight, "max": max_weight, "temp": temperature},
    }


# ==================================================================
# P2: 三资产归一化评分层（Normalized Scoring Layer）
# ==================================================================

def get_normalized_scores(window_years=None):
    """
    P2: 将三资产评分归一化为统一维度（value/risk/momentum），
    输出可直接比较的跨资产评分。

    评分维度：
      value_score (0-100): 估值分数（越低越便宜）
      risk_score (0-100):  数据可信度风险（fallback越多风险越高）
      momentum_score:      近期评分变化趋势（预留接口）

    统一分数 = 0.6 * value + 0.3 * risk + 0.1 * momentum
    """
    overview = get_valuation_overview(window_years=window_years)
    assets = overview["assets"]

    normalized = {}
    for at in ["nasdaq", "dividend", "gold"]:
        d = assets[at]
        metrics = d.get("metrics", [])

        # 1) Value Score：就是当前的估值分数（0-100，越低越便宜）
        value_score = d.get("score", 50.0) or 50.0

        # 2) Risk Score：基于数据可信度
        # full → 低风险(0-30), limited → 中风险(30-60), fallback → 高风险(60-100)
        reliability_scores = []
        for m in metrics:
            rel = m.get("reliability", "fallback")
            if rel == "full":
                reliability_scores.append(20.0)
            elif rel == "limited":
                reliability_scores.append(45.0)
            elif rel == "derived":
                reliability_scores.append(35.0)
            else:
                reliability_scores.append(70.0)

        risk_score = sum(reliability_scores) / len(reliability_scores) if reliability_scores else 50.0

        # 3) Momentum Score：基于评分近期变化（预留，当前fallback到0）
        # TODO: 当积累足够历史评分数据后，计算评分变化趋势
        momentum_score = 50.0  # 中性

        # 统一标准化分数
        unified_score = 0.6 * value_score + 0.3 * risk_score + 0.1 * momentum_score
        unified_score = max(0.0, min(100.0, unified_score))

        normalized[at] = {
            "asset": at,
            "label": ASSET_LABELS.get(at, at),
            "value_score": round(value_score, 1),
            "risk_score": round(risk_score, 1),
            "momentum_score": round(momentum_score, 1),
            "unified_score": round(unified_score, 1),
            "band": d.get("band"),
            "invest_multiplier": d.get("invest_multiplier", 1.0),
        }

    return normalized


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from pprint import pprint
    overview = get_valuation_overview()
    pprint(overview)
    print("\n=== 组合建议 (基础金额 ¥1000) ===")
    for item in get_portfolio_suggestion(1000.0):
        print(f"  {item['label']:<10s} 分数 {item['score']:>5.1f}  {item['band']:<8s}  ¥{item['amount']:>8.2f}  ({item['ratio']}%)  x{item['multiplier']}")
    print("\n=== V7 资金分配引擎 ===")
    v7 = allocate_capital_v7(10000.0)
    print(f"宏观状态: {v7['regime']['regime_cn']} ({v7['regime']['regime']})")
    print(f"统一利率锚: {v7['global_rate']['rate']}%")
    for item in v7['allocations']:
        print(f"  {item['label']:<10s} 权重 {item['weight']:>5.1f}%  ¥{item['amount']:>9.2f}  吸引力={item['attractiveness']:.1f}")
