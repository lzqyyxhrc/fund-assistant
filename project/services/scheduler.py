"""
内置定时任务调度服务
使用 APScheduler 实现定时任务，配合文件锁和日期去重避免重复执行

防重机制（三重保障）：
1. PID 文件锁：确保全局只有一个 scheduler 进程实例
2. 日期执行标记：每个任务每天只执行一次（写入 .scheduler_state.json）
3. 任务级互斥锁：防止同一任务被并发执行多次
"""

import threading
import time
import json
import os
import atexit
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# ---------- 全局配置 ----------
_SCHEDULER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(_SCHEDULER_DIR, exist_ok=True)

_PID_FILE = os.path.join(_SCHEDULER_DIR, "scheduler.pid")
_STATE_FILE = os.path.join(_SCHEDULER_DIR, "scheduler_state.json")

# ---------- 全局调度器实例 ----------
scheduler = None
_scheduler_lock = threading.Lock()
_task_locks = {}  # 任务级锁：{job_id: threading.Lock()}
_initialized = False


# ---------- 辅助函数：文件锁 / PID ----------
def _write_pid():
    """写入当前 PID 到文件，返回 True 表示成功获取锁"""
    try:
        # 检查已有 PID 是否存活
        if os.path.exists(_PID_FILE):
            try:
                with open(_PID_FILE, "r") as f:
                    old_pid = f.read().strip()
                if old_pid and old_pid.isdigit():
                    old_pid = int(old_pid)
                    # Windows: 用 tasklist 检查；其他: 用 os.kill(pid, 0)
                    try:
                        os.kill(old_pid, 0)
                        # 进程仍存活，检查是否是自己
                        if old_pid == os.getpid():
                            return True
                        print(f"[Scheduler] PID {old_pid} 仍在运行，拒绝重复启动")
                        return False
                    except OSError:
                        # 进程不存在，继续
                        pass
            except Exception:
                pass

        # 写入新 PID
        with open(_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"[Scheduler] 写入 PID 文件失败: {e}")
        return False


def _clear_pid():
    """清除 PID 文件"""
    try:
        if os.path.exists(_PID_FILE):
            with open(_PID_FILE, "r") as f:
                pid_in_file = f.read().strip()
            if pid_in_file and pid_in_file.isdigit() and int(pid_in_file) == os.getpid():
                os.remove(_PID_FILE)
    except Exception:
        pass


# ---------- 辅助函数：日期级执行标记 ----------
def _load_state():
    """加载执行状态"""
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"last_executed": {}}


def _save_state(state):
    """保存执行状态"""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Scheduler] 保存状态失败: {e}")


def _should_run_today(job_id):
    """检查任务今天是否已执行过。返回 True=应该执行，False=今天已执行过"""
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    last = state.get("last_executed", {}).get(job_id)
    if last == today:
        print(f"[Scheduler] 任务 {job_id} 今天({today})已执行过，跳过")
        return False
    return True


def _mark_executed_today(job_id):
    """标记任务今天已执行"""
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    if "last_executed" not in state:
        state["last_executed"] = {}
    state["last_executed"][job_id] = today
    _save_state(state)


# ---------- 调度器核心 ----------
def _register_jobs(sched):
    """向指定调度器注册所有定时任务"""
    # 每日早上 10:00 执行定投
    sched.add_job(
        _safe_execute,
        args=["daily_invest", execute_daily_invest],
        trigger=CronTrigger(hour=10, minute=0),
        id="daily_invest",
        name="每日定投",
        replace_existing=True,
        misfire_grace_time=300,  # 5 分钟容差
        max_instances=1,
        coalesce=True,
    )

    # 每日晚上 22:00 执行份额确认
    sched.add_job(
        _safe_execute,
        args=["confirm_shares", execute_confirm_shares],
        trigger=CronTrigger(hour=22, minute=0),
        id="confirm_shares",
        name="确认份额",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
        coalesce=True,
    )

    # 每日晚上 22:10 生成日报
    sched.add_job(
        _safe_execute,
        args=["daily_report", execute_daily_report],
        trigger=CronTrigger(hour=22, minute=10),
        id="daily_report",
        name="生成日报",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
        coalesce=True,
    )


def _safe_execute(job_id, func):
    """安全执行任务：日期去重 + 任务级锁"""
    # 1. 先检查日期去重
    if not _should_run_today(job_id):
        return

    # 2. 获取任务级锁（防止同一任务被并发执行）
    if job_id not in _task_locks:
        _task_locks[job_id] = threading.Lock()
    task_lock = _task_locks[job_id]

    if not task_lock.acquire(blocking=False):
        print(f"[Scheduler] 任务 {job_id} 正在执行中，跳过本次调度")
        return

    try:
        # 3. 执行任务
        func()
        # 4. 成功执行后标记今天已执行
        _mark_executed_today(job_id)
    finally:
        task_lock.release()


def _init_scheduler():
    """惰性初始化调度器（仅在显式调用 start_scheduler 时创建）"""
    global scheduler, _initialized

    with _scheduler_lock:
        if _initialized and scheduler is not None and scheduler.running:
            return

        # 获取 PID 锁
        if not _write_pid():
            print("[Scheduler] 未能获取全局 PID 锁，不启动调度器")
            scheduler = None
            return

        try:
            print("[Scheduler] 启动定时任务调度器...")
            scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
            _register_jobs(scheduler)
            scheduler.start()
            _initialized = True
            print("[Scheduler] 启动成功，已注册任务:")
            for job in scheduler.get_jobs():
                print(f"  - {job.name}({job.id}) | {job.trigger}")
        except Exception as e:
            print(f"[Scheduler] 启动失败: {e}")
            scheduler = None
            _initialized = False


# ---------- 任务实现 ----------
def execute_daily_invest():
    """每日定投任务（早上 10:00 执行）"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始执行每日定投任务...")

    try:
        from services.storage import load_config, save_config
        from services.fund_fetcher import get_fund_batch_net_value
        from services.auto_invest import load_auto_invest_config, check_and_execute_auto_invest

        funds_config = load_config()
        auto_config = load_auto_invest_config()

        if not auto_config.get("enabled", False):
            print("自动定投未启用")
            return

        all_codes = []
        for category in ["nasdaq", "dividend", "gold"]:
            for fund in funds_config["funds"].get(category, []):
                if fund["code"]:
                    all_codes.append(fund["code"])

        if not all_codes:
            print("未配置基金代码")
            return

        print("获取基金净值...")
        net_values = get_fund_batch_net_value(all_codes)

        if not net_values:
            print("未能获取基金净值")
            return

        print("成功获取基金净值")

        transactions, total_amount = check_and_execute_auto_invest(funds_config, net_values)

        if transactions:
            print(f"自动定投完成！共投入 ¥{total_amount:.2f}")
            save_config(funds_config)
            print("持仓已更新")

            for trans in transactions:
                print(f"  - {trans['name']}: ¥{trans['amount']:.2f}")
        else:
            print("今日无需定投（可能已执行或未到定投时间）")

    except Exception as e:
        print(f"定投任务执行失败: {str(e)}")
        import traceback
        traceback.print_exc()


def execute_confirm_shares():
    """每日份额确认任务（晚上 22:00 执行）"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始执行份额确认任务...")

    try:
        from services.storage import load_config, save_config
        from services.fund_fetcher import get_fund_batch_net_value
        from services.auto_invest import confirm_pending_shares

        funds_config = load_config()

        all_codes = []
        for category in ["nasdaq", "dividend", "gold"]:
            for fund in funds_config["funds"].get(category, []):
                if fund["code"]:
                    all_codes.append(fund["code"])

        if not all_codes:
            print("未配置基金代码")
            return

        print("获取基金净值...")
        net_values = get_fund_batch_net_value(all_codes)

        if not net_values:
            print("未能获取基金净值")
            return

        print("成功获取基金净值")
        print("检查待确认份额...")

        confirmed_count = confirm_pending_shares(funds_config, net_values)

        if confirmed_count > 0:
            print(f"已确认 {confirmed_count} 笔待确认份额")
            save_config(funds_config)
            print("持仓已更新")
        else:
            print("暂无到期待确认份额")

    except Exception as e:
        print(f"确认份额任务执行失败: {str(e)}")
        import traceback
        traceback.print_exc()


def execute_daily_report():
    """每日生成日报任务（晚上 22:10 执行）"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始执行日报生成任务...")

    try:
        from services.auto_invest import load_auto_invest_config

        auto_config = load_auto_invest_config()
        api_key = auto_config.get("report_api_key", "")
        feishu_webhook = auto_config.get("feishu_webhook", "")

        from daily_report import generate_daily_report, save_report, send_to_feishu

        print("生成投资日报...")
        report = generate_daily_report(api_key=api_key)

        if report:
            save_report(report)
            print("日报已生成")

            if feishu_webhook:
                print("发送到飞书...")
                if send_to_feishu(report, feishu_webhook):
                    print("已发送到飞书")
                else:
                    print("飞书发送失败")
        else:
            print("日报生成失败")

    except Exception as e:
        print(f"日报生成任务执行失败: {str(e)}")
        import traceback
        traceback.print_exc()


# ---------- 外部 API ----------
def start_scheduler():
    """启动定时任务调度器"""
    _init_scheduler()
    return scheduler is not None and scheduler.running


def stop_scheduler():
    """停止定时任务调度器"""
    global scheduler, _initialized

    with _scheduler_lock:
        if scheduler is None:
            print("[Scheduler] 调度器未启动")
            return False

        try:
            print("[Scheduler] 停止定时任务调度器...")
            scheduler.shutdown(wait=True)
        except Exception as e:
            print(f"[Scheduler] 停止时出错: {e}")
        finally:
            scheduler = None
            _initialized = False
            _clear_pid()
            print("[Scheduler] 已停止")
            return True


def is_scheduler_running():
    """检查调度器是否运行中"""
    with _scheduler_lock:
        return scheduler is not None and scheduler.running


def get_scheduler_jobs():
    """获取所有定时任务信息"""
    with _scheduler_lock:
        if scheduler is None:
            return []

        jobs = []
        for job in scheduler.get_jobs():
            next_run_time = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run_time": next_run_time.strftime("%Y-%m-%d %H:%M:%S") if next_run_time else None,
                "running": False,
            })
        return jobs


def run_job_now(job_id):
    """立即执行指定任务（不受日期去重限制，手动触发）"""
    job_mapping = {
        "daily_invest": execute_daily_invest,
        "confirm_shares": execute_confirm_shares,
        "daily_report": execute_daily_report,
    }

    if job_id not in job_mapping:
        return False, f"未找到任务: {job_id}"

    try:
        job_mapping[job_id]()
        # 手动执行后也标记今天已执行（避免定时任务再次触发）
        _mark_executed_today(job_id)
        return True, f"任务 {job_id} 已立即执行"
    except Exception as e:
        return False, f"执行失败: {str(e)}"


# ---------- 程序退出清理 ----------
@atexit.register
def _cleanup_on_exit():
    _clear_pid()


# 注意：不再在模块加载时自动启动调度器！
# 需通过 UI 按钮显式调用 start_scheduler()，或在 app.py 中启动。

if __name__ == "__main__":
    print("测试定时任务调度器...")
    start_scheduler()

    print("\n当前任务列表:")
    for job in get_scheduler_jobs():
        print(f"  {job['name']} - 下次执行: {job['next_run_time']}")

    input("\n按回车停止调度器...")
    stop_scheduler()
    print("测试完成")
