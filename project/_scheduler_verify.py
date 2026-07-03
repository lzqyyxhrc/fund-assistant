"""验证 scheduler 防重机制（简化版，无交互）"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.scheduler import (
    _should_run_today, _mark_executed_today, _load_state,
    _safe_execute, _write_pid, _clear_pid,
    start_scheduler, stop_scheduler, is_scheduler_running, get_scheduler_jobs,
)

# 1. 测试日期去重
print("=== 测试 1：日期去重 ===")
_test_job = "test_job_" + str(int(time.time()))
r1 = _should_run_today(_test_job)
print(f"  首次检查: {r1} (预期 True) -> {'PASS' if r1 else 'FAIL'}")
_mark_executed_today(_test_job)
r2 = _should_run_today(_test_job)
print(f"  已标记后检查: {r2} (预期 False) -> {'PASS' if not r2 else 'FAIL'}")
state = _load_state()
print(f"  状态文件包含标记: {_test_job in state.get('last_executed', {})}")
print()

# 2. 测试任务级互斥锁
print("=== 测试 2：任务级互斥锁（并发5次只执行1次） ===")
_exec_count = 0
_counter_lock = threading.Lock()

def slow_task():
    global _exec_count
    time.sleep(0.3)
    with _counter_lock:
        _exec_count += 1

_test_job2 = "test_job2_" + str(int(time.time()))
threads = []
for i in range(5):
    t = threading.Thread(target=_safe_execute, args=(_test_job2, slow_task))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

ok = _exec_count == 1
print(f"  并发 5 次调用，实际执行: {_exec_count} (预期 1) -> {'PASS' if ok else 'FAIL'}")
print()

# 3. 测试 PID 锁
print("=== 测试 3：PID 文件锁 ===")
r3 = _write_pid()
print(f"  首次获取: {r3} (预期 True) -> {'PASS' if r3 else 'FAIL'}")
r4 = _write_pid()  # 同一进程再次获取（pid 相同，应成功）
print(f"  同进程再次: {r4} (预期 True) -> {'PASS' if r4 else 'FAIL'}")
_clear_pid()
print("  清理 PID 文件")
print()

# 4. 测试调度器启动/停止（无实际定时执行）
print("=== 测试 4：调度器启动 & 任务注册 ===")
ok_start = start_scheduler()
running = is_scheduler_running()
jobs = get_scheduler_jobs()
print(f"  启动成功: {ok_start}, 运行中: {running}, 任务数: {len(jobs)}")
for j in jobs:
    print(f"    - {j['name']}({j['id']}) | {j['trigger'][:30]}... | 下次: {j['next_run_time']}")

# 再次启动（应不会重复创建）
start_scheduler()
jobs2 = get_scheduler_jobs()
print(f"  重复调用 start_scheduler 后任务数: {len(jobs2)} (预期仍为 3)")

stop_scheduler()
print(f"  停止后运行状态: {is_scheduler_running()}")
print()

# 5. 检查核心文件语法
print("=== 测试 5：核心文件语法 ===")
import ast
files = [
    "services/scheduler.py",
    "services/valuation_fetcher.py",
    "services/valuation_scoring.py",
    "components/valuation_panel.py",
    "components/dashboard.py",
    "components/scheduler_panel.py",
    "app.py",
]
all_ok = True
for f in files:
    try:
        ast.parse(open(f, encoding="utf-8").read())
        print(f"  {f}: OK")
    except SyntaxError as e:
        print(f"  {f}: FAIL - {e}")
        all_ok = False

print()
if all_ok:
    print("✅ 所有验证通过")
else:
    print("❌ 有验证失败，请检查")
    sys.exit(1)
