# 💰 基金智能定投再平衡助手

> 一个覆盖 **纳指100 / 中证红利 / 黄金** 三资产的个人定投系统，包含
> 估值评分、宏观状态识别、资金分配引擎、自动定投、AI 日报生成 等完整能力。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-red?logo=streamlit)
![SQLite](https://img.shields.io/badge/DB-SQLite-lightgrey?logo=sqlite)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ 核心特性

### 🧭 V7 三层资产配置引擎

从"单纯估值评分"进化为"资产配置机器"：

```
┌─────────────────────────────────────┐
│  Macro Regime（宏观状态层）           │  4种状态：Risk-On / Off / Stagflation / Neutral
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│  Asset Models（三资产独立模型）       │  纳指 / 中证红利 V6.1 / 黄金 V5.1
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│  Normalized Scoring（归一化评分层）   │  value + risk + momentum
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│  Capital Allocation Engine（资金分配） │  softmax + min/max 约束
└─────────────────────────────────────┘
```

### 📊 三资产估值体系

| 资产 | 权重设计 | 数据源 |
|------|---------|--------|
| **纳指100** | PE 70% + PEG 30% | 蛋卷基金（10年历史百分位） |
| **中证红利 V6.1** | 估值 60% + 利率锚 25% + 结构稳定性 15% | 蛋卷 + 中国10Y国债 + CPI |
| **黄金 V5.1** | 实际利率 50% + Gold/PPI 30% + 金银比 20% | FRED + FMP |

### 🌐 宏观修正

- 10Y美债 / TIPS实际利率 / VIX / 美元指数 / PPI / CPI 同比
- Dividend Spread = 股息率 − max(国债, CPI)  ← 通胀调整版
- Global Rate Anchor = 0.7 × US实际利率 + 0.3 × 中国10Y

### 🤖 自动化能力

- ✅ 每日自动抓取估值 + 净值数据（内置调度器）
- ✅ 自动定投（可配置金额/频率/策略）
- ✅ 待确认份额机制（下单 T 日 → 确认 T+1）
- ✅ 一键组合再平衡建议
- ✅ **AI 投资日报**（接入 DeepSeek，可选）
- ✅ 飞书 Webhook 推送

---

## 📸 界面预览

- **仪表盘**：总资产、持仓收益、昨日收益、资产配置饼图
- **持仓明细**：编辑模式一键调整份额/成本
- **估值面板**：三资产评分卡片 + 历史百分位走势
- **自动定投**：策略配置 + 定投历史
- **指数分析**：三资产累计收益对比

---

## 🚀 快速开始

### 1. 环境准备

```bash
git clone https://github.com/lzqyyxhrc/fund-assistant.git
cd fund-assistant
pip install -r project/requirements.txt
```

需要 Python 3.10 或更高版本。

### 2. 配置 API Key（`.env`）

```bash
# 复制模板并编辑
cp .env.example .env
```

编辑 `.env` 填入你的 API Key：

```env
FRED=你的_FRED_API_KEY          # https://fred.stlouisfed.org/docs/api/api_key.html
FMP=你的_FMP_API_KEY            # https://site.financialmodelingprep.com
DANJUAN_COOKIE=device_id=...    # 蛋卷登录 Cookie（浏览器 DevTools 抓取）
DEEPSEEK_API_KEY=sk-xxx         # 可选，用于 AI 日报
FEISHU_WEBHOOK=https://...      # 可选，日报推送到飞书群
```

> ⚠️ `.env` 已在 `.gitignore` 中，绝不会被上传到 Git。所有 Key 都是可选的，缺失时对应功能会自动跳过。

### 3. 启动应用

**方式 A：命令行**

```bash
cd project
streamlit run app.py
```

**方式 B：Windows 一键启动（无黑窗）**

双击项目根目录：

- `启动基金助手.vbs` → 静默启动，自动打开浏览器
- `创建桌面快捷方式.vbs` → 一次运行，桌面出现带图标的启动/停止快捷方式

启动后浏览器访问：`http://localhost:8501`

---

## 📁 项目结构

```
基金助手/
├── project/
│   ├── app.py                     # Streamlit 主入口
│   ├── daily_report.py            # AI 日报生成
│   ├── auto_invest_cron.py        # 定时任务入口
│   ├── backtest.py                # 策略回测
│   ├── services/
│   │   ├── valuation_scoring.py   # V7 估值评分 + 资金分配引擎
│   │   ├── valuation_fetcher.py   # FRED/FMP/蛋卷/AkShare 数据抓取
│   │   ├── auto_invest.py         # 自动定投逻辑
│   │   ├── scheduler.py           # 内置调度器
│   │   ├── fund_fetcher.py        # 基金净值抓取（AkShare/天天基金）
│   │   ├── database.py            # SQLite 持久化
│   │   └── storage.py             # 配置管理
│   ├── views/
│   │   ├── dashboard_page.py      # 仪表盘
│   │   ├── valuation_page.py      # 估值面板
│   │   ├── positions_page.py      # 持仓管理
│   │   ├── auto_invest_page.py    # 自动定投
│   │   └── index_analysis_page.py # 指数分析
│   └── components/                # 复用 UI 组件
├── .env.example                   # 环境变量模板
├── .gitignore
├── 启动基金助手.vbs                # Windows 静默启动
├── 停止基金助手.bat                # 关闭服务
└── 创建桌面快捷方式.vbs             # 创建带图标快捷方式
```

---

## 📚 数据源

| 数据源 | 用途 | 频率 | 是否需要 Key |
|--------|------|------|--------------|
| **蛋卷基金** | 纳指/红利 PE/PB/PEG/ROE/股息率 | 日频 | 需要登录 Cookie |
| **FRED** | 美债利率 / TIPS / VIX / 美元指数 / PPI / CPI | 日频/月频 | 免费申请 |
| **FMP** | 黄金/白银现货价 | 日频 | 免费申请 |
| **AkShare** | 中国 10Y 国债 / 基金净值 | 日频 | 无需 |
| **天天基金** | 基金净值兜底 | 日频 | 无需 |
| **DeepSeek**（可选） | AI 日报生成 | 按需 | 需要 Key |

---

## 🧮 估值体系版本演进

| 版本 | 关键升级 |
|------|---------|
| V4 → V5 | 全部改为历史百分位法；黄金体系去掉绝对金价，改用 Gold/PPI |
| V5 → V6 | 红利加入 ROE 盈利锚、Dividend Spread 利率锚、PE/PB mismatch 结构风险 |
| V6 → V6.1 | ROE 改为调节因子（避免 PE/PB/ROE 数学闭环重复计分）；结构风险改为 Penalty |
| V6.1 → V7 | 新增宏观状态层 + 统一利率锚 + Softmax 资金分配引擎 |

详细的估值方法论请参考代码注释：[valuation_scoring.py](project/services/valuation_scoring.py)。

---

## 🔧 常用命令

```bash
# 启动 Streamlit
streamlit run project/app.py

# 一次性拉取最新估值数据
python project/init_valuation_history.py

# 生成 AI 日报（需要 DEEPSEEK_API_KEY）
python project/daily_report.py

# 手动执行自动定投任务
python project/auto_invest_cron.py --invest

# 确认待确认份额（T+1）
python project/auto_invest_cron.py --confirm

# 策略回测
python project/backtest.py
```

---

## 🛡️ 安全提示

- 所有 API Key、Cookie 存储在本地 `.env` 或 SQLite 数据库中，**不会**上传 Git
- 首次 clone 后必须自行创建 `.env`（参考 `.env.example`）
- 建议开启数据库文件的操作系统级加密（NTFS 加密或 BitLocker）
- 不要把 `fund_assistant.db` / `auto_invest_config.json` 提交到公开仓库

---

## 📝 License

MIT © 2026 lzqyyxhrc

---

## 🙏 致谢

- [Streamlit](https://streamlit.io) - 无痛的 Python Web UI
- [AkShare](https://akshare.readthedocs.io) - 高质量金融数据接口
- [FRED](https://fred.stlouisfed.org) - 美联储圣路易斯分行经济数据
- [蛋卷基金](https://danjuanfunds.com) - 优质的指数估值分位数据

---

> **免责声明**：本项目仅用于个人投资参考和学习交流，所有估值方法、评分模型、定投倍数均基于历史数据统计，**不构成任何投资建议**。投资决策请以自身风险偏好为准，市场有风险，入市需谨慎。
