"""
定时任务管理面板
"""

import streamlit as st
from services.scheduler import (
    start_scheduler,
    stop_scheduler,
    is_scheduler_running,
    get_scheduler_jobs,
    run_job_now
)

def render_scheduler_panel():
    """渲染定时任务管理面板"""
    st.subheader("⏰ 定时任务管理")
    
    # 检查调度器状态
    running = is_scheduler_running()
    
    col1, col2 = st.columns(2)
    with col1:
        if running:
            st.success("✅ 定时任务服务已启动")
        else:
            st.warning("⏸️ 定时任务服务未启动")
    
    with col2:
        if running:
            if st.button("停止服务", type="secondary"):
                stop_scheduler()
                st.rerun()
        else:
            if st.button("启动服务", type="primary"):
                start_scheduler()
                st.rerun()
    
    if running:
        # 显示任务列表
        st.markdown("### 📋 当前任务")
        
        jobs = get_scheduler_jobs()
        if jobs:
            for job in jobs:
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
                    with col1:
                        st.write(f"**{job['name']}**")
                    with col2:
                        st.write(f"触发规则: {job['trigger']}")
                    with col3:
                        st.write(f"下次执行: {job['next_run_time']}")
                    with col4:
                        if st.button(f"立即执行", key=f"run_{job['id']}", width='stretch'):
                            success, msg = run_job_now(job['id'])
                            if success:
                                st.success(msg)
                            else:
                                st.error(msg)
                            st.rerun()
        else:
            st.info("暂无定时任务")
        
        # 显示任务说明
        st.markdown("### 📝 任务说明")
        st.markdown("""
        | 任务名称 | 执行时间 | 说明 |
        |---------|---------|------|
        | 每日定投 | 早上 10:00 | 自动执行定投操作 |
        | 确认份额 | 晚上 22:00 | 确认到期的待确认份额 |
        | 生成日报 | 晚上 22:10 | 生成并发送投资日报 |
        """)
        
        st.markdown("### 💡 使用说明")
        st.markdown("""
        1. **启动服务**: 点击「启动服务」按钮启动内置定时任务
        2. **立即执行**: 点击任务右侧的「立即执行」按钮可手动触发任务
        3. **停止服务**: 点击「停止服务」按钮停止定时任务
        4. **保持运行**: 需要保持Streamlit应用持续运行才能执行定时任务
        
        > **注意**: 内置定时任务需要Streamlit应用持续运行。如果需要后台运行，建议使用nohup或服务管理器。
        """)
    else:
        st.info("启动定时任务服务后，系统将自动执行以下任务：")
        st.markdown("""
        - **每日 10:00**: 执行自动定投
        - **每日 22:00**: 确认待确认份额
        - **每日 22:10**: 生成投资日报
        """)
