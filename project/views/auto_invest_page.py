import streamlit as st
from services.auto_invest import load_auto_invest_config, save_auto_invest_config, load_invest_history


def format_money(amount, pattern="¥{:,.2f}"):
    if st.session_state.get("privacy_mode", False):
        return "****"
    return pattern.format(amount)


def render_auto_invest():
    config = st.session_state.config

    st.header("🔄 定投计划")

    auto_config = load_auto_invest_config()

    if "auto_invest_funds" not in st.session_state:
        st.session_state.auto_invest_funds = auto_config.get("auto_invest_funds", [])

    if "auto_edit_mode" not in st.session_state:
        st.session_state.auto_edit_mode = False

    col_edit, _ = st.columns([1, 4])
    with col_edit:
        if st.button("编辑模式" if not st.session_state.auto_edit_mode else "退出编辑", type="primary" if st.session_state.auto_edit_mode else "secondary", key="auto_invest_edit_mode_btn"):
            st.session_state.auto_edit_mode = not st.session_state.auto_edit_mode
            st.rerun()

    st.markdown("**定投基金列表**")
    auto_funds = st.session_state.auto_invest_funds

    if st.session_state.auto_edit_mode:
        for i, fund in enumerate(auto_funds):
            with st.container():
                col_code, col_amount, col_del = st.columns([3, 2, 1])

                with col_code:
                    fund["code"] = st.text_input("基金代码", fund.get("code", ""), key=f"auto_edit_code_{i}", label_visibility="collapsed")

                with col_amount:
                    fund["amount"] = st.number_input("每日金额", value=fund.get("amount", 0), min_value=0, step=10, key=f"auto_edit_amount_{i}", label_visibility="collapsed")

                with col_del:
                    if st.button("删除", key=f"auto_edit_del_{i}", type="secondary"):
                        st.session_state.auto_invest_funds.pop(i)
                        st.rerun()

                st.divider()

        if st.button("+ 添加定投基金", key="auto_edit_add"):
            st.session_state.auto_invest_funds.append({"code": "", "amount": 0})
            st.rerun()

        if st.button("保存定投计划", key="auto_edit_save", type="primary"):
            auto_config["auto_invest_funds"] = st.session_state.auto_invest_funds
            save_auto_invest_config(auto_config)
            st.success("定投计划已保存！")

    else:
        if auto_funds:
            data = []
            for fund in auto_funds:
                fund_name = ""
                for category in ["nasdaq", "dividend", "gold"]:
                    for f in config["funds"].get(category, []):
                        if f["code"] == fund["code"]:
                            fund_name = f["name"]
                            break

                if st.session_state.get("privacy_mode", False):
                    data.append({
                        "基金代码": fund["code"],
                        "基金名称": fund_name or "-",
                        "每日金额": "****"
                    })
                else:
                    data.append({
                        "基金代码": fund["code"],
                        "基金名称": fund_name or "-",
                        "每日金额": f"¥{fund.get('amount', 0):,.0f}"
                    })
            st.dataframe(data, width='stretch', hide_index=True)
        else:
            st.write("暂无定投计划")

    total_daily = sum(f.get("amount", 0) for f in auto_funds)
    if st.session_state.get("privacy_mode", False):
        st.markdown(f"**每日定投总额**: ****")
    else:
        st.markdown(f"**每日定投总额**: ¥{total_daily:,}")

    st.divider()
    
    st.subheader("📊 投资记录")
    
    invest_history = load_invest_history()
    
    if invest_history:
        col1, col2 = st.columns(2)
        with col1:
            total_invested = sum(record.get("amount", 0) for record in invest_history)
            st.metric("累计投入", format_money(total_invested))
        with col2:
            total_transactions = len(invest_history)
            st.metric("交易次数", total_transactions)
        
        if not st.session_state.get("privacy_mode", False):
            data = []
            for record in invest_history:
                data.append({
                    "日期": record.get("date", ""),
                    "基金代码": record.get("fund_code", ""),
                    "金额": f"¥{record.get('amount', 0):,.2f}",
                    "类型": record.get("type", "")
                })
            st.dataframe(data, width='stretch', hide_index=True)
        else:
            st.info("隐私模式下隐藏投资记录详情")
    else:
        st.info("暂无投资记录")

    st.divider()
    
    st.subheader("⏰ 定时任务管理")
    
    from components.scheduler_panel import render_scheduler_panel
    render_scheduler_panel()