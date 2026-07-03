import json
import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "fund_assistant.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _read_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def init_db():
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS portfolio_targets (
                category TEXT PRIMARY KEY,
                target_weight REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fund_positions (
                code TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                shares REAL NOT NULL DEFAULT 0,
                cost_price REAL NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                amount REAL NOT NULL,
                pending_date TEXT,
                net_value_date TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(fund_code, amount, pending_date, net_value_date, status)
            );

            CREATE TABLE IF NOT EXISTS auto_invest_config (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS auto_invest_plans (
                code TEXT PRIMARY KEY,
                amount REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS invest_records (
                trade_date TEXT PRIMARY KEY,
                total_amount REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS invest_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                confirm_date TEXT,
                net_value_date TEXT,
                category TEXT,
                code TEXT NOT NULL,
                name TEXT,
                amount REAL NOT NULL,
                shares REAL NOT NULL DEFAULT 0,
                net_value REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(trade_date, code, amount, net_value_date)
            );

            CREATE TABLE IF NOT EXISTS fund_nav_history (
                fund_code TEXT NOT NULL,
                record_date TEXT NOT NULL,
                nav_date TEXT NOT NULL,
                net_value REAL NOT NULL,
                change_pct REAL NOT NULL DEFAULT 0,
                updated_at TEXT,
                source TEXT,
                PRIMARY KEY (fund_code, record_date)
            );

            CREATE TABLE IF NOT EXISTS index_prices (
                index_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL NOT NULL,
                volume REAL,
                source_file TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (index_code, trade_date)
            );

            CREATE TABLE IF NOT EXISTS valuation_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_type TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_label TEXT,
                trade_date TEXT NOT NULL,
                value REAL,
                source TEXT,
                raw_json TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(asset_type, metric_name, trade_date)
            );
            """
        )
        migrated = conn.execute("SELECT value FROM app_meta WHERE key='json_migrated'").fetchone()
        if not migrated:
            migrate_json_to_db(conn)
            conn.execute(
                "INSERT OR REPLACE INTO app_meta(key, value) VALUES('json_migrated', '1')"
            )


def migrate_json_to_db(conn):
    config = _read_json(BASE_DIR / "funds_config.json", None)
    if config:
        save_config_db(config, conn)

    auto_config = _read_json(BASE_DIR / "auto_invest_config.json", None)
    if auto_config:
        save_auto_invest_config_db(auto_config, conn)

    history = _read_json(BASE_DIR / "invest_history.json", None)
    if history:
        save_invest_history_db(history, conn)

    nav_history = _read_json(BASE_DIR / "net_value_history.json", None)
    if nav_history:
        save_net_value_history_db(nav_history, conn)

    investment_config = _read_json(BASE_DIR / "investment_config.json", None)
    if investment_config:
        conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) VALUES(?, ?)",
            ("investment_amount", json.dumps(investment_config.get("amount", 1000), ensure_ascii=False))
        )

    threshold_config = _read_json(BASE_DIR / "threshold_config.json", None)
    if threshold_config:
        conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) VALUES(?, ?)",
            ("rebalance_threshold", json.dumps(threshold_config.get("rebalance_threshold", 0.02), ensure_ascii=False))
        )


def ensure_db():
    init_db()


def normalize_config(config):
    for category in config.get("funds", {}):
        for fund in config["funds"][category]:
            if "pending_shares" in fund and "pending_amount" not in fund:
                pending_cost = fund.get("pending_cost_price", 0.0)
                fund["pending_amount"] = fund["pending_shares"] * pending_cost

            if "pending_amount" in fund and fund["pending_amount"] > 0 and "pending_orders" not in fund:
                pending_date = fund.get("pending_date")
                net_value_date = fund.get("net_value_date", pending_date)
                fund["pending_orders"] = [{
                    "amount": fund["pending_amount"],
                    "pending_date": pending_date,
                    "net_value_date": net_value_date
                }]

            for key in ["pending_shares", "pending_cost_price", "pending_amount", "pending_date", "net_value_date", "pending_confirm_date"]:
                fund.pop(key, None)
    return config


def load_config_db():
    ensure_db()
    with get_connection() as conn:
        targets_rows = conn.execute("SELECT category, target_weight FROM portfolio_targets").fetchall()
        fund_rows = conn.execute(
            "SELECT category, code, name, shares, cost_price FROM fund_positions ORDER BY category, rowid"
        ).fetchall()
        pending_rows = conn.execute(
            "SELECT fund_code, amount, pending_date, net_value_date FROM pending_orders WHERE status='pending' ORDER BY id"
        ).fetchall()

    config = {
        "targets": {"nasdaq": 0.4, "dividend": 0.4, "gold": 0.2},
        "funds": {"nasdaq": [], "dividend": [], "gold": []}
    }
    for row in targets_rows:
        config["targets"][row["category"]] = row["target_weight"]

    pending_map = {}
    for row in pending_rows:
        pending_map.setdefault(row["fund_code"], []).append({
            "amount": row["amount"],
            "pending_date": row["pending_date"],
            "net_value_date": row["net_value_date"]
        })

    for row in fund_rows:
        category = row["category"]
        config["funds"].setdefault(category, [])
        fund = {
            "code": row["code"],
            "name": row["name"],
            "shares": row["shares"],
            "cost_price": row["cost_price"]
        }
        if row["code"] in pending_map:
            fund["pending_orders"] = pending_map[row["code"]]
        config["funds"][category].append(fund)

    return config


def save_config_db(config, conn=None):
    config = normalize_config(config)
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.execute("DELETE FROM portfolio_targets")
        conn.execute("DELETE FROM pending_orders")
        conn.execute("DELETE FROM fund_positions")

        for category, weight in config.get("targets", {}).items():
            conn.execute(
                "INSERT INTO portfolio_targets(category, target_weight) VALUES(?, ?)",
                (category, float(weight))
            )

        for category, funds in config.get("funds", {}).items():
            for fund in funds:
                code = fund.get("code", "").strip()
                if not code:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fund_positions(code, category, name, shares, cost_price, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        category,
                        fund.get("name", code),
                        float(fund.get("shares", 0) or 0),
                        float(fund.get("cost_price", 0) or 0),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                )
                for order in fund.get("pending_orders", []):
                    amount = float(order.get("amount", 0) or 0)
                    if amount <= 0:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO pending_orders(fund_code, amount, pending_date, net_value_date, status)
                        VALUES(?, ?, ?, ?, 'pending')
                        """,
                        (code, amount, order.get("pending_date"), order.get("net_value_date"))
                    )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def load_auto_invest_config_db():
    ensure_db()
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM auto_invest_config").fetchall()
        plans = conn.execute("SELECT code, amount FROM auto_invest_plans ORDER BY rowid").fetchall()

    config = {
        "enabled": False,
        "last_invest_date": None,
        "auto_invest_funds": []
    }
    for row in rows:
        config[row["key"]] = json.loads(row["value"])
    config["auto_invest_funds"] = [
        {"code": row["code"], "amount": row["amount"]} for row in plans
    ]
    return config


def save_auto_invest_config_db(config, conn=None):
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.execute("DELETE FROM auto_invest_config")
        conn.execute("DELETE FROM auto_invest_plans")
        for key, value in config.items():
            if key == "auto_invest_funds":
                continue
            conn.execute(
                "INSERT OR REPLACE INTO auto_invest_config(key, value) VALUES(?, ?)",
                (key, json.dumps(value, ensure_ascii=False))
            )
        for plan in config.get("auto_invest_funds", []):
            code = plan.get("code", "").strip()
            if code:
                conn.execute(
                    "INSERT OR REPLACE INTO auto_invest_plans(code, amount) VALUES(?, ?)",
                    (code, float(plan.get("amount", 0) or 0))
                )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def load_invest_history_db():
    ensure_db()
    with get_connection() as conn:
        records = conn.execute("SELECT trade_date, total_amount FROM invest_records ORDER BY trade_date").fetchall()
        txns = conn.execute("SELECT * FROM invest_transactions ORDER BY trade_date, id").fetchall()

    txn_map = {}
    for row in txns:
        txn_map.setdefault(row["trade_date"], []).append({
            "date": row["trade_date"],
            "confirm_date": row["confirm_date"],
            "net_value_date": row["net_value_date"],
            "category": row["category"],
            "code": row["code"],
            "name": row["name"],
            "amount": row["amount"],
            "shares": row["shares"],
            "net_value": row["net_value"],
            "status": row["status"]
        })

    return [
        {
            "date": row["trade_date"],
            "total_amount": row["total_amount"],
            "transactions": txn_map.get(row["trade_date"], [])
        }
        for row in records
    ]


def save_invest_history_db(history, conn=None):
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.execute("DELETE FROM invest_transactions")
        conn.execute("DELETE FROM invest_records")
        for record in history:
            trade_date = record.get("date")
            if not trade_date:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO invest_records(trade_date, total_amount) VALUES(?, ?)",
                (trade_date, float(record.get("total_amount", 0) or 0))
            )
            for txn in record.get("transactions", []):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO invest_transactions(
                        trade_date, confirm_date, net_value_date, category, code, name, amount, shares, net_value, status
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        txn.get("date", trade_date),
                        txn.get("confirm_date"),
                        txn.get("net_value_date"),
                        txn.get("category"),
                        txn.get("code"),
                        txn.get("name", txn.get("code")),
                        float(txn.get("amount", 0) or 0),
                        float(txn.get("shares", 0) or 0),
                        float(txn.get("net_value", 0) or 0),
                        txn.get("status", "pending")
                    )
                )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def load_net_value_history_db():
    ensure_db()
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM fund_nav_history ORDER BY fund_code, record_date").fetchall()

    history = {}
    for row in rows:
        history.setdefault(row["fund_code"], {})[row["record_date"]] = {
            "date": row["nav_date"],
            "net_value": row["net_value"],
            "change": row["change_pct"],
            "updated_at": row["updated_at"]
        }
    return history


def save_net_value_history_db(history, conn=None):
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.execute("DELETE FROM fund_nav_history")
        for fund_code, fund_history in history.items():
            for record_date, data in fund_history.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fund_nav_history(fund_code, record_date, nav_date, net_value, change_pct, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fund_code,
                        record_date,
                        data.get("date", record_date),
                        float(data.get("net_value", 0) or 0),
                        float(data.get("change", 0) or 0),
                        data.get("updated_at")
                    )
                )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def upsert_nav(fund_code, record_date, nav_date, net_value, change, updated_at=None, source=None):
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO fund_nav_history(fund_code, record_date, nav_date, net_value, change_pct, updated_at, source)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fund_code,
                record_date,
                nav_date,
                float(net_value),
                float(change),
                updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source
            )
        )


def get_nav_by_record_date(fund_code, record_date):
    ensure_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM fund_nav_history WHERE fund_code=? AND record_date=?",
            (fund_code, record_date)
        ).fetchone()
    if not row:
        return None
    return {
        "date": row["nav_date"],
        "net_value": row["net_value"],
        "change": row["change_pct"],
        "updated_at": row["updated_at"]
    }


def get_fund_history_db(fund_code):
    ensure_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM fund_nav_history WHERE fund_code=? ORDER BY record_date",
            (fund_code,)
        ).fetchall()
    return {
        row["record_date"]: {
            "date": row["nav_date"],
            "net_value": row["net_value"],
            "change": row["change_pct"],
            "updated_at": row["updated_at"]
        }
        for row in rows
    }


def import_index_csv(index_code, file_path):
    ensure_db()
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    if 'date' not in df.columns or 'close' not in df.columns:
        return 0
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    source_file = Path(file_path).name
    rows = []
    for _, row in df.iterrows():
        close = row.get('close')
        if pd.isna(close):
            continue
        rows.append((
            index_code,
            row['date'],
            None if pd.isna(row.get('open')) else float(row.get('open')),
            None if pd.isna(row.get('high')) else float(row.get('high')),
            None if pd.isna(row.get('low')) else float(row.get('low')),
            float(close),
            None if pd.isna(row.get('volume')) else float(row.get('volume')),
            source_file,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO index_prices(
                index_code, trade_date, open, high, low, close, volume, source_file, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows
        )
    return len(rows)


def load_index_prices(index_code):
    ensure_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close, volume FROM index_prices WHERE index_code=? ORDER BY trade_date",
            (index_code,)
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        'date': pd.to_datetime(row['trade_date']),
        'open': row['open'],
        'high': row['high'],
        'low': row['low'],
        'close': row['close'],
        'volume': row['volume']
    } for row in rows])


def has_index_prices(index_code):
    ensure_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM index_prices WHERE index_code=?",
            (index_code,)
        ).fetchone()
    return bool(row and row['cnt'] > 0)


def get_setting(key, default=None):
    ensure_db()
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    return json.loads(row["value"])


def set_setting(key, value):
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) VALUES(?, ?)",
            (key, json.dumps(value, ensure_ascii=False))
        )


# ---------- 估值指标 valuation_metrics ----------

def upsert_valuation_metric(asset_type, metric_name, trade_date, value,
                            metric_label=None, source=None, raw_json=None):
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO valuation_metrics(
                asset_type, metric_name, metric_label, trade_date, value, source, raw_json, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_type, metric_name, metric_label, trade_date,
                float(value) if value is not None else None,
                source,
                json.dumps(raw_json, ensure_ascii=False) if raw_json is not None else None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )


def bulk_upsert_valuation_metrics(rows):
    """批量 upsert。rows = [(asset_type, metric_name, trade_date, value, metric_label, source, raw_json)]"""
    ensure_db()
    if not rows:
        return 0
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO valuation_metrics(
                asset_type, metric_name, metric_label, trade_date, value, source, raw_json, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r[0], r[1], r[4] if len(r) > 4 else None, r[2],
                    float(r[3]) if r[3] is not None else None,
                    r[5] if len(r) > 5 else None,
                    json.dumps(r[6], ensure_ascii=False) if len(r) > 6 and r[6] is not None else None,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                for r in rows
            ]
        )
    return len(rows)


def get_latest_valuation(asset_type, metric_name):
    ensure_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM valuation_metrics
            WHERE asset_type=? AND metric_name=?
            ORDER BY trade_date DESC LIMIT 1
            """,
            (asset_type, metric_name)
        ).fetchone()
    if not row:
        return None
    return dict(row)


def get_valuation_history(asset_type, metric_name, start_date=None, limit=None):
    ensure_db()
    sql = "SELECT * FROM valuation_metrics WHERE asset_type=? AND metric_name=?"
    params = [asset_type, metric_name]
    if start_date:
        sql += " AND trade_date >= ?"
        params.append(start_date)
    sql += " ORDER BY trade_date"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_latest_valuation_metric(asset_type, metric_name):
    """获取指定资产和指标的最新值"""
    ensure_db()
    sql = """
    SELECT value FROM valuation_metrics 
    WHERE asset_type=? AND metric_name=? 
    ORDER BY trade_date DESC LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(sql, [asset_type, metric_name]).fetchone()
    return row["value"] if row else None


def set_csi_dividend_valuation(pe, pb, dividend_yield):
    """手动设置中证红利估值指标"""
    ensure_db()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = [
        ("dividend", "csi_div_pe_manual", today, pe, "中证红利静态市盈率(手动)", "手动维护", None),
        ("dividend", "csi_div_pb_manual", today, pb, "中证红利市净率(手动)", "手动维护", None),
        ("dividend", "csi_div_yield_manual", today, dividend_yield, "中证红利股息率%(手动)", "手动维护", None),
    ]
    bulk_upsert_valuation_metrics(rows)
