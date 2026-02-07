import streamlit as st
import requests
import re
import pandas as pd
from datetime import datetime
import time
import urllib3
from bs4 import BeautifulSoup
from collections import Counter
import numpy as np
import plotly.graph_objects as go

# 1. 系統設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="賓果 AI 星雲神諭版", page_icon="🌌", layout="wide")

# CSS: 星雲紫 + 手機版優化 (RWD)
st.markdown("""
    <style>
    .stApp { background-color: #050014; color: #e0ccff; font-family: 'Segoe UI', sans-serif; }
    
    /* 電腦版預設標題 */
    .nebula-header {
        text-align: center;
        font-size: 3em;
        font-weight: 900;
        background: linear-gradient(to right, #d946ef, #8b5cf6, #06b6d4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        filter: drop-shadow(0 0 15px rgba(139, 92, 246, 0.5));
        margin-bottom: 20px;
        letter-spacing: 3px;
    }

    /* 核心球體容器 */
    .orb-wrapper {
        display: flex;
        justify-content: center;
        gap: 50px;
        margin: 40px 0;
        perspective: 800px;
    }
    
    /* 星雲球 */
    .nebula-ball {
        width: 120px;
        height: 120px;
        line-height: 120px;
        border-radius: 50%;
        text-align: center;
        font-size: 3.5em;
        font-weight: 900;
        color: #fff;
        background: radial-gradient(circle at 30% 30%, #d946ef, #4c1d95);
        box-shadow: 0 0 30px #d946ef, inset 0 0 15px #fff;
        border: 2px solid #e9d5ff;
        position: relative;
        animation: float 4s ease-in-out infinite;
        z-index: 10;
    }
    
    .ball-sub {
        transform: scale(0.9);
        background: radial-gradient(circle at 30% 30%, #8b5cf6, #1e1b4b);
        box-shadow: 0 0 20px #8b5cf6;
        animation-delay: 1s;
    }

    @keyframes float {
        0% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
        100% { transform: translateY(0px); }
    }

    .rank-label {
        text-align: center;
        font-size: 0.85em;
        color: #c084fc;
        margin-top: 15px;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }
    
    /* --- 手機版專屬優化 (Mobile Optimization) --- */
    @media (max-width: 768px) {
        /* 手機標題縮小，避免換行太醜 */
        .nebula-header { font-size: 1.8em; letter-spacing: 1px; margin-bottom: 10px; }
        
        /* 手機上球的間距縮小，方便單手滑動 */
        .orb-wrapper { margin: 15px 0; gap: 20px; }
        
        /* 手機球體稍微縮小，適配窄螢幕 */
        .nebula-ball { width: 100px; height: 100px; line-height: 100px; font-size: 2.8em; }
        
        /* 隱藏不必要的裝飾邊距 */
        .block-container { padding-top: 2rem; padding-left: 1rem; padding-right: 1rem; }
    }
    /* ------------------------------------------- */

    /* 歷史表格優化 */
    div[data-testid="stDataFrame"] {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 10px;
        padding: 5px;
    }

    </style>
""", unsafe_allow_html=True)

# Session State
if 'history_data' not in st.session_state: st.session_state.history_data = []
if 'last_run_time' not in st.session_state: st.session_state.last_run_time = time.time()
if 'sim_results' not in st.session_state: st.session_state.sim_results = None

# --- 1. 核心抓取 ---
def fetch_data():
    url = "https://www.pilio.idv.tw/bingo/list.asp"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10, verify=False)
        res.encoding = 'big5'
        if res.status_code != 200: return []
        
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.find_all('tr')
        results = []
        seen_ids = set()
        
        for row in rows:
            text = row.get_text(strip=True)
            id_match = re.search(r'(11[5-6]\d{6})', text)
            if id_match:
                draw_id = id_match.group(1)
                if not (115000000 < int(draw_id) < 116000000): continue
                if draw_id in seen_ids: continue
                nums = re.findall(r'\d+', text)
                clean_nums = []
                for n in nums:
                    val = int(n)
                    if str(val) == draw_id: continue
                    if 1 <= val <= 80 and val not in clean_nums: clean_nums.append(val)
                if len(clean_nums) >= 20:
                    ball_20 = sorted(clean_nums[:20])
                    if ball_20[:5] != [1,2,3,4,5]:
                        results.append({"id": draw_id, "nums": ball_20})
                        seen_ids.add(draw_id)
        return results[:30]
    except:
        return []

# --- 2. 蒙地卡羅模擬 ---
def run_simulation(data):
    if not data: return None, None, None, None
    
    probs = np.ones(81) * 1.0 
    all_nums = [n for d in data for n in d['nums']]
    counts = Counter(all_nums)
    last_draw = data[0]['nums']
    
    attr_scores = {}
    
    for n in range(1, 81):
        hot_score = counts[n] * 2.5
        probs[n] += hot_score
        
        rep_score = 20.0 if n in last_draw else 0
        probs[n] += rep_score
        
        grav_score = (counts.get(n-1, 0) + counts.get(n+1, 0)) * 0.5
        probs[n] += grav_score
        
        chaos_score = np.random.uniform(0, 5)
        probs[n] += chaos_score
        
        attr_scores[n] = [hot_score, rep_score, grav_score, chaos_score]

    weights = probs[1:] 
    weight_sum = np.sum(weights)
    weights = weights / weight_sum if weight_sum > 0 else np.ones(80)/80
    population = np.arange(1, 81)
    
    sim_counts = Counter()
    for _ in range(10000):
        draw = np.random.choice(population, size=20, replace=False, p=weights)
        sim_counts.update(draw)
    
    top_3 = [n for n, c in sim_counts.most_common(3)]
    rates = {n: (sim_counts[n] / 10000) * 100 for n in top_3}
    
    return top_3, rates, dict(sim_counts), attr_scores

# --- 3. 更新與 UI ---
def update():
    data = fetch_data()
    if data:
        st.session_state.history_data = data
        st.session_state.last_run_time = time.time()
        top_3, rates, raw_sims, attrs = run_simulation(data)
        if top_3:
            st.session_state.sim_results = {"top_3": top_3, "rates": rates, "raw": raw_sims, "attrs": attrs}
        return True
    return False

# --- 介面呈現 ---
st.markdown("<div class='nebula-header'>🌌 NEBULA ORACLE SYSTEM</div>", unsafe_allow_html=True)

if not st.session_state.history_data:
    with st.spinner("正在穿越事件視界..."):
        update()

# 側邊欄 (手機上會自動收合)
with st.sidebar:
    st.markdown("### 🌌 神諭控制台")
    if st.button("🚀 啟動預知模擬", type="primary"):
        update()
        st.rerun()
    auto = st.checkbox("自動同步", value=True)
    if auto:
        diff = time.time() - st.session_state.last_run_time
        st.caption(f"下次同步：{300 - int(diff)}s")

# 主畫面
if st.session_state.sim_results:
    res = st.session_state.sim_results
    top_3 = res['top_3']
    rates = res['rates']
    attrs = res['attrs']
    latest_id = st.session_state.history_data[0]['id']
    
    # 1. 核心球體
    st.markdown(f"<div style='text-align:center; color:#e0ccff;'>目標期別：<span style='color:#d946ef; font-weight:bold; font-size:1.3em;'>{int(latest_id)+1}</span></div>", unsafe_allow_html=True)
    
    # 為了手機優化，我們用 columns 但手機會自動變成垂直排列
    c1, c2, c3 = st.columns([1, 1, 1])
    
    # Alpha (最強) 放在中間 (手機上會是第一個)
    with c2: 
        st.markdown(f"""<div class='orb-wrapper'><div class='nebula-ball'>{top_3[0]:02d}</div></div>""", unsafe_allow_html=True)
        st.markdown(f"<div class='rank-label' style='color:#d946ef;'>Alpha Star ({rates[top_3[0]]:.1f}%)</div>", unsafe_allow_html=True)
    
    # Beta 和 Gamma 隨後 (手機上會在 Alpha 下方)
    col_sub1, col_sub2 = st.columns(2)
    with col_sub1:
        st.markdown(f"""<div class='orb-wrapper'><div class='nebula-ball ball-sub'>{top_3[1]:02d}</div></div>""", unsafe_allow_html=True)
        st.markdown(f"<div class='rank-label'>Beta ({rates[top_3[1]]:.1f}%)</div>", unsafe_allow_html=True)
    with col_sub2:
        st.markdown(f"""<div class='orb-wrapper'><div class='nebula-ball ball-sub'>{top_3[2]:02d}</div></div>""", unsafe_allow_html=True)
        st.markdown(f"<div class='rank-label'>Gamma ({rates[top_3[2]]:.1f}%)</div>", unsafe_allow_html=True)

    # 2. AI 推理雷達圖
    st.markdown("---")
    st.subheader("🕸️ AI 推理雷達")
    
    categories = ['熱度 (Hot)', '連莊 (Repeat)', '重力 (Gravity)', '混沌 (Chaos)']
    fig = go.Figure()
    colors = ['#d946ef', '#8b5cf6', '#06b6d4']
    for i, n in enumerate(top_3):
        vals = attrs[n]
        max_val = max(vals) if max(vals) > 0 else 1
        vals_norm = [v/max_val for v in vals]
        fig.add_trace(go.Scatterpolar(r=vals_norm, theta=categories, fill='toself', name=f'{n:02d}', line_color=colors[i], opacity=0.6))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1], showticklabels=False), bgcolor='#0f172a'),
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white'),
        margin=dict(l=30, r=30, t=10, b=10), # 手機邊距優化
        height=300,
        showlegend=True,
        legend=dict(orientation="h", y=-0.2)
    )
    st.plotly_chart(fig, use_container_width=True)
        
    # 3. 歷史驗證儀表板
    st.markdown("---")
    st.subheader("📜 歷史驗證 (Validation)")
    
    df = pd.DataFrame(st.session_state.history_data)
    df['總分'] = df['nums'].apply(sum)
    df['大小'] = df['總分'].apply(lambda x: "大" if x >= 810 else "小")
    df['單雙'] = df['nums'].apply(lambda x: "單" if sum(n%2!=0 for n in x) >= 11 else "雙")
    df['號碼'] = df['nums'].apply(lambda x: " ".join([f"{n:02d}" for n in x]))
    
    st.dataframe(
        df[['id', '總分', '大小', '單雙', '號碼']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.TextColumn("期別", width="small"),
            "號碼": st.column_config.TextColumn("開獎號碼", width="medium"), # 手機上調整寬度
            "總分": st.column_config.ProgressColumn(
                "總分",
                format="%d",
                min_value=600,
                max_value=1000,
            ),
        }
    )
    
    st.markdown(f"<div style='text-align:center; color:#555; margin-top:20px; font-size:0.8em;'>SYSTEM v3.2 MOBILE READY</div>", unsafe_allow_html=True)

# 自動刷新
time.sleep(1)
if time.time() - st.session_state.last_run_time > 300:
    update()
    st.rerun()
else:
    st.rerun()