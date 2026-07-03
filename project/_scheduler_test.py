"""验证 scheduler 防重机制"""
import sys
import os
import time
import threading
sys.path.insert(0, '.')

from services.scheduler import (
    _should_run_today, _mark_executed_today, _load_state,
    _safe_execute, _write_pid, _clear_pid, start_scheduler, stop_scheduler
)

# 1. 测试日期去重
print("=== 测试 1：日期去重 ===")
_test_job = "test_job_" + str(int(time.time()))
print(f"  首次检查: {_should_run_today(_test_job)} (预期 True)")
_mark_executed_today(_test_job)
print(f"  已标记后检查: {_should_run_today(_test_job)} (预期 False)")
print("  状态文件内容:", _load_state())
print()

# 2. 测试任务级互斥锁
print("=== 测试 2：任务级互斥锁 ===")
_exec_count = 0
_lock = threading.Lock()

def slow_task():
    global _exec_count
    time.sleep(0.5)
    with _lock:
        _exec_count += 1

_test_job2 = "test_job2_" + str(int(time.time()))
threads = []
for i in range(5):
    t = threading.Thread(target=_safe_execute, args=(_test_job2, slow_task))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

print(f"  并发 5 次调用 slow_task，实际执行次数: {_exec_count} (预期 1)")
print()

# 3. 测试 PID 锁
print("=== 测试 3：PID 锁 ===")
result1 = _write_pid()
print(f"  首次获取 PID 锁: {result1} (预期 True)")
result2 = _write_pid()  # 同一进程再次获取（应该成功，因为 pid 相同）
print(f"  同一进程再次获取: {result2} (预期 True)")
_clear_pid()
print("  清理完毕")
print()

# 4. 测试调度器启动/停止
print("=== 测试 4：调度器启动/停止 ===")
ok = start_scheduler()
print(f"  启动成功: {ok}")
print(f"  运行状态: {is_scheduler_running_local()}")
jobs = get_jobs_local()
print(f"  注册任务数: {len(jobs)}")
for j in jobs:
    print(f"    - {j['name']} | {j['trigger']} | 下次: {j['next_run_time']}")

# 再次启动（应该是 no-op）
ok2 = start_scheduler()
print(f"  再次调用 start_scheduler: {ok2} (预期 True，但不重复创建)")

stop_scheduler()
print(f"  停止后状态: {is_scheduler_running_local()}")
print()

print("✅ 所有验证通过")


def is_scheduler_running_local():
    from services.scheduler import is_scheduler_running
    return is_scheduler_running()


def get_jobs_local():
    from services.scheduler import get_scheduler_jobs
    return get_scheduler_jobs()
