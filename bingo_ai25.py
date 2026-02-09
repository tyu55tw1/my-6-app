import streamlit as st
import pandas as pd
import requests
import re
import urllib3
from bs4 import BeautifulSoup
from collections import Counter
import plotly.express as px

# 1. 系統設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="賓果 AI 旗艦版 v3.4", page_icon="🎰", layout="wide")

# CSS 美化
st.markdown("""
    <style>
    .stApp { background-color: #f4f6f9; }
    .header-box {
        background: linear-gradient(135deg, #2c3e50, #4ca1af);
        padding: 20px; border-radius: 15px; color: white; text-align: center;
        margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 2.5em; font-weight: 900; letter-spacing: 2px; }
    .header-info { font-size: 1.2em; margin-top: 10px; background: rgba(255,255,255,0.2); padding: 5px 15px; border-radius: 20px; display: inline-block; }
    .header-sub { font-size: 0.9em; color: #ddd; margin-top: 5px; }
    
    .ball {
        display: inline-block; width: 32px; height: 32px; line-height: 32px;
        border-radius: 50%; text-align: center; font-weight: bold; margin: 3px;
        font-size: 14px; box-shadow: 1px 1px 3px rgba(0,0,0,0.2);
    }
    .ball-hit { background: #ffeb3b; color: #d35400; border: 2px solid #e67e22; }
    .ball-miss { background: #ecf0f1; color: #bdc3c7; }
    .ball-normal { background: #3498db; color: white; }
    
    /* 歷史紀錄容器樣式 */
    .history-container {
        height: 400px;
        overflow-y: auto;
        padding-right: 10px;
        border: 1px solid #ddd;
        border-radius: 5px;
        background-color: #fff;
    }
    .history-row {
        padding: 8px; border-bottom: 1px solid #eee; display: flex; align-items: center;
    }
    .history-row.win { background-color: #f0fff4; }
    .history-row.loss { background-color: #ffffff; }
    </style>
""", unsafe_allow_html=True)

# --- 核心數據函數 ---
@st.cache_data(ttl=30)
def fetch_data():
    url = "https://www.pilio.idv.tw/bingo/list.asp"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5, verify=False)
        res.encoding = 'big5'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        data = []
        seen = set()
        for row in soup.find_all('tr'):
            text = row.get_text(strip=True)
            id_match = re.search(r'(11[3-9]\d{6})', text)
            if id_match:
                draw_id = int(id_match.group(1))
                if draw_id in seen: continue
                nums = [int(n) for n in re.findall(r'\d+', text) if int(n) <= 80 and int(n) != draw_id]
                if len(nums) >= 20:
                    data.append({"期數": draw_id, "號碼": nums[:20]})
                    seen.add(draw_id)
        
        return pd.DataFrame(data).sort_values("期數", ascending=False).reset_index(drop=True)
    except: return pd.DataFrame()

def get_stats(df, periods=20):
    subset = df.head(periods)
    all_nums = [n for sublist in subset['號碼'] for n in sublist]
    counts = Counter(all_nums)
    
    hot = counts.most_common(10)
    cold = []
    for i in range(1, 81):
        if i not in counts: cold.append((i, 0))
        else: cold.append((i, counts[i]))
    cold.sort(key=lambda x: x[1])
    return hot, cold[:10]

# --- 主程式 ---
df = fetch_data()

# 頂部資訊看板
if not df.empty:
    last_draw = df.iloc[0]
    current_period = last_draw['期數']
    
    start_period = current_period + 1
    end_period = current_period + 10
    
    st.markdown(f"""
    <div class='header-box'>
        <div class='header-title'>🎰 賓果 AI 旗艦版 v3.4</div>
        <div class='header-info'>
            📊 最新開獎：<b>{current_period}</b> 期 <br>
            🎯 追號目標：<b>{start_period} ~ {end_period}</b> 期 (10期內)
        </div>
        <div class='header-sub'>💡 建議策略：此組號碼適用於未來 10 期內的養號/追號計畫</div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.error("❌ 無法連線至資料庫，請檢查網路狀態。")
    st.stop()

# --- 佈局 ---
col_left, col_right = st.columns([1, 2])

# === 左側：操作區 ===
with col_left:
    st.subheader("🛠️ 戰術設定")
    star = st.slider("選擇星數 (1-10)", 1, 10, 3)
    
    st.markdown("### 🤖 AI 參謀")
    hot_list, cold_list = get_stats(df, 50)
    
    if "last_ai_mode" not in st.session_state: st.session_state.last_ai_mode = "手動輸入"
    
    ai_mode = st.radio("自動填入策略：", ["手動輸入", "🔥 追擊熱門", "❄️ 抄底冷門", "⚖️ 冷熱平衡"])
    
    force_update = False
    if ai_mode != st.session_state.last_ai_mode:
        st.session_state.last_ai_mode = ai_mode
        force_update = True
    
    target_nums = []
    if ai_mode == "🔥 追擊熱門":
        target_nums = [x[0] for x in hot_list[:star]]
    elif ai_mode == "❄️ 抄底冷門":
        target_nums = [x[0] for x in cold_list[:star]]
    elif ai_mode == "⚖️ 冷熱平衡":
        half = star // 2
        target_nums = [x[0] for x in hot_list[:half]] + [x[0] for x in cold_list[:(star-half)]]
    
    st.markdown("### 📝 號碼確認")
    user_nums = []
    cols = st.columns(5)
    
    for i in range(star):
        key_name = f"bingo_{i}"
        
        if force_update:
            if i < len(target_nums):
                st.session_state[key_name] = str(target_nums[i])
            else:
                if key_name in st.session_state: del st.session_state[key_name]

        with cols[i % 5]:
            val = st.session_state.get(key_name, "")
            inp = st.text_input(f"#{i+1}", value=val, key=key_name, max_chars=2, label_visibility="collapsed", placeholder=f"{i+1}")
            if inp.strip().isdigit(): user_nums.append(int(inp))
            
    if force_update: st.rerun()

    st.markdown("---")
    backtest_range = st.select_slider("回測期數範圍", options=[10, 20, 50, 100], value=20)
    run_btn = st.button("🚀 執行戰術回測", type="primary", use_container_width=True)

# === 右側：戰情室 ===
with col_right:
    tab1, tab2, tab3 = st.tabs(["📊 市場行情", "📜 歷史開獎", "📈 回測報告"])
    
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 🔥 熱門號碼 (近50期)")
            hot_df = pd.DataFrame(hot_list, columns=["號碼", "次數"])
            fig_hot = px.bar(hot_df, x='號碼', y='次數', color='次數', color_continuous_scale='Reds')
            st.plotly_chart(fig_hot, use_container_width=True, height=250)
        with c2:
            st.markdown("#### ❄️ 冷門號碼 (近50期)")
            cold_df = pd.DataFrame(cold_list, columns=["號碼", "次數"])
            fig_cold = px.bar(cold_df, x='號碼', y='次數', color='次數', color_continuous_scale='Blues_r')
            st.plotly_chart(fig_cold, use_container_width=True, height=250)

    with tab2:
        st.markdown(f"#### 📜 最近 100 期開獎紀錄")
        history_display = df.head(100).copy()
        
        def format_balls(nums):
            html = ""
            for n in nums:
                html += f"<span class='ball ball-normal'>{n:02d}</span>"
            return html

        # 分批渲染歷史開獎
        st.markdown("<div style='height:500px; overflow-y:auto; padding-right:5px;'>", unsafe_allow_html=True)
        for _, row in history_display.iterrows():
            row_html = f"""
            <div style='background:white; padding:10px; margin-bottom:8px; border-radius:8px; border-left:5px solid #3498db; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
                <div style='font-weight:bold; color:#2c3e50; margin-bottom:5px;'>第 {row['期數']} 期</div>
                <div>{format_balls(row['號碼'])}</div>
            </div>
            """
            st.markdown(row_html, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with tab3:
        if run_btn:
            if len(user_nums) != star:
                st.warning(f"⚠️ 請填滿 {star} 個號碼才能回測！")
            else:
                target_df = df.head(backtest_range)
                history = []
                total_hits = 0
                win_count = 0
                
                for _, row in target_df.iterrows():
                    draw_nums = set(row['號碼'])
                    hits = len(set(user_nums) & draw_nums)
                    total_hits += hits
                    
                    is_win = hits >= (star/2 + 0.5)
                    if is_win: win_count += 1
                    
                    res_html = ""
                    for n in sorted(user_nums):
                        cls = "ball-hit" if n in draw_nums else "ball-miss"
                        res_html += f"<span class='ball {cls}'>{n:02d}</span>"
                    
                    history.append({
                        "期數": row['期數'],
                        "命中": hits,
                        "球號": res_html,
                        "狀態": "🎉" if is_win else "❌",
                        "CSS": "win" if is_win else "loss"
                    })
                
                k1, k2, k3 = st.columns(3)
                k1.metric("平均命中", f"{total_hits / backtest_range:.1f} 顆")
                k2.metric("勝率 (過半)", f"{win_count / backtest_range * 100:.0f}%")
                k3.metric("最高命中", f"{max([h['命中'] for h in history])} 顆")
                
                st.divider()
                st.markdown("#### 📜 詳細戰績")
                
                # --- 這裡進行了重要的修改：分批渲染 ---
                st.markdown("<div class='history-container'>", unsafe_allow_html=True)
                
                for h in history:
                    row_html = f"""
                    <div class='history-row {h['CSS']}'>
                        <span style='width:90px; font-weight:bold; color:#555;'>{h['期數']}</span>
                        <span style='width:40px; font-size:1.2em;'>{h['狀態']}</span>
                        <span style='flex-grow:1;'>{h['球號']}</span>
                        <span style='font-weight:bold; color:#d35400;'>中 {h['命中']}</span>
                    </div>
                    """
                    # 每次只渲染一行，確保正確解析
                    st.markdown(row_html, unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("👈 請在左側設定號碼後，點擊「執行戰術回測」查看報告。")

# 底部狀態列
st.markdown("---")
st.caption(f"資料來源：台灣彩券賓果賓果 | 自動更新頻率：每 5 分鐘 | 目前模式：{ai_mode} (v3.4 渲染修復版)")