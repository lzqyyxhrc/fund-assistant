import streamlit as st
from services.database import get_setting
from services.valuation_fetcher import set_api_key, get_api_key


def render_valuation():
    st.header("🎯 估值评分系统")

    # ---- 蛋卷接口状态提示（Cookie 过期反馈） ----
    status = get_setting("danjuan:status", None)
    status_msg = get_setting("danjuan:status_msg", "")
    status_at = get_setting("danjuan:status_at", "")
    if status == "error":
        st.error(f"⚠️ 蛋卷数据源异常：{status_msg}（{status_at}）\n\n请在下方展开「蛋卷 Cookie 设置」更新 Cookie。")
    elif status == "ok":
        st.caption(f"✅ 蛋卷数据源正常（{status_at}）")

    # ---- 蛋卷 Cookie 设置 ----
    with st.expander("🔑 蛋卷 Cookie 设置（数据源，过期时需更新）", expanded=(status == "error")):
        st.info(
            "纳指/中证红利的 PE、PB、PEG、股息率及10年历史百分位均来自蛋卷基金官方接口，"
            "需要登录 Cookie。Cookie 通常 7-30 天过期，过期后请按以下步骤更新："
        )
        st.markdown(
            "1. 浏览器登录 [蛋卷基金](https://danjuanfunds.com) \n"
            "2. 打开任一指数估值页（如 NDX），按 F12 → Network \n"
            "3. 找到 `detail/NDX` 请求，复制其请求头中的完整 **Cookie** \n"
            "4. 粘贴到下方保存"
        )
        current_cookie = get_api_key("danjuan_cookie", "")
        masked = (current_cookie[:30] + "...") if current_cookie else "（未设置）"
        st.caption(f"当前 Cookie：{masked}")
        new_cookie = st.text_area("粘贴新的 Cookie", value="", height=80,
                                  placeholder="device_id=...; xq_a_token=...; u=...")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 保存 Cookie", type="primary"):
                if new_cookie.strip():
                    set_api_key("danjuan_cookie", new_cookie.strip())
                    st.success("Cookie 已保存！点击右侧按钮重新获取数据验证。")
                    st.rerun()
                else:
                    st.warning("请先粘贴 Cookie")
        with col2:
            if st.button("🔄 重新获取全部估值", type="secondary"):
                from services.valuation_fetcher import fetch_all_valuations
                with st.spinner("正在更新估值数据..."):
                    fetch_all_valuations()
                st.success("估值数据已更新！")
                st.rerun()

    st.divider()

    from components.valuation_panel import render_valuation_panel
    render_valuation_panel()
