"""
内置定时任务调度服务
使用APScheduler实现定时任务，无需依赖操作系统定时任务
"""

import threading
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 全局调度器实例
scheduler = None
scheduler_lock = threading.Lock()

# 延迟初始化标记，避免循环导入问题
_initialized = False

def _init_scheduler():
    """延迟初始化调度器（在所有函数定义完成后调用）"""
    global scheduler, _initialized
    
    with scheduler_lock:
        if _initialized or scheduler is not None:
            return
        
        try:
            print("模块加载时自动启动定时任务调度器...")
            scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
            
            # 添加定时任务
            # 每日早上10:00执行定投
            scheduler.add_job(
                execute_daily_invest,
                CronTrigger(hour=10, minute=0),
                id="daily_invest",
                name="每日定投",
                replace_existing=True
            )
            
            # 每日晚上22:00执行份额确认
            scheduler.add_job(
                execute_confirm_shares,
                CronTrigger(hour=22, minute=0),
                id="confirm_shares",
                name="确认份额",
                replace_existing=True
            )
            
            # 每日晚上22:10生成日报
            scheduler.add_job(
                execute_daily_report,
                CronTrigger(hour=22, minute=10),
                id="daily_report",
                name="生成日报",
                replace_existing=True
            )
            
            scheduler.start()
            _initialized = True
            print("定时任务调度器自动启动成功")
        except Exception as e:
            print(f"自动启动调度器失败: {e}")
            scheduler = None

def execute_daily_invest():
    """每日定投任务（早上10:00执行）"""
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
    """每日份额确认任务（晚上22:00执行）"""
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
    """每日生成日报任务（晚上22:10执行）"""
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

def start_scheduler():
    """启动定时任务调度器（兼容手动启动）"""
    global scheduler
    
    with scheduler_lock:
        if scheduler is not None and scheduler.running:
            print("定时任务调度器已启动")
            return False
        
        # 重新创建调度器
        print("启动定时任务调度器...")
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        
        # 添加定时任务
        # 每日早上10:00执行定投
        scheduler.add_job(
            execute_daily_invest,
            CronTrigger(hour=10, minute=0),
            id="daily_invest",
            name="每日定投",
            replace_existing=True
        )
        
        # 每日晚上22:00执行份额确认
        scheduler.add_job(
            execute_confirm_shares,
            CronTrigger(hour=22, minute=0),
            id="confirm_shares",
            name="确认份额",
            replace_existing=True
        )
        
        # 每日晚上22:10生成日报
        scheduler.add_job(
            execute_daily_report,
            CronTrigger(hour=22, minute=10),
            id="daily_report",
            name="生成日报",
            replace_existing=True
        )
        
        # 启动调度器
        scheduler.start()
        print("定时任务调度器启动成功")
        print("已注册的定时任务:")
        for job in scheduler.get_jobs():
            print(f"  - {job.name}: {job.trigger}")
        
        return True

def stop_scheduler():
    """停止定时任务调度器"""
    global scheduler
    
    with scheduler_lock:
        if scheduler is None:
            print("定时任务调度器未启动")
            return False
        
        print("停止定时任务调度器...")
        scheduler.shutdown(wait=True)
        scheduler = None
        print("定时任务调度器已停止")
        
        return True

def is_scheduler_running():
    """检查调度器是否运行中"""
    with scheduler_lock:
        return scheduler is not None and scheduler.running

def get_scheduler_jobs():
    """获取所有定时任务信息"""
    with scheduler_lock:
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
                "running": False  # APScheduler的Job对象没有running属性
            })
        
        return jobs

def run_job_now(job_id):
    """立即执行指定任务"""
    # 创建任务映射
    job_mapping = {
        "daily_invest": execute_daily_invest,
        "confirm_shares": execute_confirm_shares,
        "daily_report": execute_daily_report
    }
    
    if job_id not in job_mapping:
        return False, f"未找到任务: {job_id}"
    
    try:
        # 直接调用任务函数
        job_mapping[job_id]()
        return True, f"任务 {job_id} 已立即执行"
    except Exception as e:
        return False, f"执行失败: {str(e)}"

# 模块加载完成后自动初始化调度器（延迟执行，确保所有函数已定义）
_init_scheduler()

# 测试代码
if __name__ == "__main__":
    print("测试定时任务调度器...")
    
    # 获取任务列表（应该已经自动启动）
    jobs = get_scheduler_jobs()
    print("\n当前任务列表:")
    for job in jobs:
        print(f"  {job['name']} - 下次执行: {job['next_run_time']}")
    
    # 等待用户输入
    input("\n按回车停止调度器...")
    
    # 停止调度器
    stop_scheduler()
    print("测试完成")
