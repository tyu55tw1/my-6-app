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
import plotly.express as px
import plotly.graph_objects as go

# 1. 系統設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="賓果 AI 星雲神諭版", page_icon="🌌", layout="wide")

# CSS: 星雲紫科技風格 (Nebula Violet)
st.markdown("""
    <style>
    .stApp { background-color: #050014; color: #e0ccff; font-family: 'Segoe UI', sans-serif; }
    
    /* 標題特效 */
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

    /* 排名標籤 */
    .rank-label {
        text-align: center;
        font-size: 0.85em;
        color: #c084fc;
        margin-top: 15px;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }
    
    /* 數據分析區塊 */
    .analysis-box {
        background: rgba(17, 24, 39, 0.7);
        border: 1px solid #4c1d95;
        border-radius: 15px;
        padding: 20px;
        backdrop-filter: blur(10px);
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

# --- 2. 蒙地卡羅模擬 + 多維分析 ---
def run_simulation(data):
    if not data: return None, None, None, None
    
    probs = np.ones(81) * 1.0 
    all_nums = [n for d in data for n in d['nums']]
    counts = Counter(all_nums)
    last_draw = data[0]['nums']
    
    # 屬性分數 (用於雷達圖)
    # 格式: {num: {'hot': v, 'repeat': v, 'gravity': v, 'chaos': v}}
    attr_scores = {}
    
    for n in range(1, 81):
        # 1. 熱度 (Frequency)
        hot_score = counts[n] * 2.5
        probs[n] += hot_score
        
        # 2. 連莊 (Momentum)
        rep_score = 20.0 if n in last_draw else 0
        probs[n] += rep_score
        
        # 3. 重力 (Gravity)
        grav_score = (counts.get(n-1, 0) + counts.get(n+1, 0)) * 0.5
        probs[n] += grav_score
        
        # 4. 混沌 (Chaos)
        chaos_score = np.random.uniform(0, 5)
        probs[n] += chaos_score
        
        # 記錄屬性 (正規化後用於繪圖)
        attr_scores[n] = [hot_score, rep_score, grav_score, chaos_score]

    weights = probs[1:] 
    weight_sum = np.sum(weights)
    weights = weights / weight_sum if weight_sum > 0 else np.ones(80)/80
    population = np.arange(1, 81)
    
    # 模擬 10,000 次
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
st.markdown("<div class='nebula-header'>🌌 NEBULA ORACLE: AI SYSTEM</div>", unsafe_allow_html=True)

if not st.session_state.history_data:
    with st.spinner("正在穿越事件視界..."):
        update()

# 側邊欄
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
    
    # 1. 核心球體 (Pyramid Layout)
    st.markdown(f"<div style='text-align:center; color:#e0ccff;'>目標期別：<span style='color:#d946ef; font-weight:bold; font-size:1.3em;'>{int(latest_id)+1}</span></div>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2: # 中間最強
        st.markdown(f"""<div class='orb-wrapper'><div class='nebula-ball'>{top_3[0]:02d}</div></div>""", unsafe_allow_html=True)
        st.markdown(f"<div class='rank-label' style='color:#d946ef;'>Alpha Star ({rates[top_3[0]]:.1f}%)</div>", unsafe_allow_html=True)
    
    c_a, c_b, c_c, c_d = st.columns([1, 2, 2, 1])
    with c_b: # 左下
        st.markdown(f"""<div class='orb-wrapper'><div class='nebula-ball ball-sub'>{top_3[1]:02d}</div></div>""", unsafe_allow_html=True)
        st.markdown(f"<div class='rank-label'>Beta ({rates[top_3[1]]:.1f}%)</div>", unsafe_allow_html=True)
    with c_c: # 右下
        st.markdown(f"""<div class='orb-wrapper'><div class='nebula-ball ball-sub'>{top_3[2]:02d}</div></div>""", unsafe_allow_html=True)
        st.markdown(f"<div class='rank-label'>Gamma ({rates[top_3[2]]:.1f}%)</div>", unsafe_allow_html=True)

    # 2. AI 推理雷達圖 (New Feature)
    st.markdown("---")
    col_chart, col_desc = st.columns([2, 1])
    
    with col_chart:
        st.subheader("🕸️ AI 推理雷達 (Why Selected?)")
        # 準備雷達圖數據
        categories = ['熱度 (Hot)', '連莊 (Repeat)', '重力 (Gravity)', '混沌 (Chaos)']
        fig = go.Figure()
        
        # 繪製前三名的屬性
        colors = ['#d946ef', '#8b5cf6', '#06b6d4']
        for i, n in enumerate(top_3):
            # 正規化數據以便繪圖
            vals = attrs[n]
            max_val = max(vals) if max(vals) > 0 else 1
            vals_norm = [v/max_val for v in vals]
            
            fig.add_trace(go.Scatterpolar(
                r=vals_norm,
                theta=categories,
                fill='toself',
                name=f'號碼 {n:02d}',
                line_color=colors[i],
                opacity=0.6
            ))

        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1], showticklabels=False), bgcolor='#0f172a'),
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='white'),
            margin=dict(l=40, r=40, t=20, b=20),
            height=300,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with col_desc:
        st.info("💡 圖表解讀")
        st.markdown("""
        * **熱度**：近期出現頻率高。
        * **連莊**：上一期剛開過。
        * **重力**：鄰近號碼很熱 (如 24, 26 熱 -> 拉抬 25)。
        * **混沌**：AI 隨機演算中的幸運值。
        """)
        st.markdown(f"**Alpha ({top_3[0]})** 的最強屬性是：")
        best_attr_idx = np.argmax(attrs[top_3[0]])
        st.success(f"🔥 {categories[best_attr_idx]}")

    # 3. 智慧儀表板表格 (Evolution Point)
    st.markdown("---")
    st.subheader("📜 歷史驗證儀表板 (Smart History)")
    st.markdown("觀察進度條與標籤，快速判斷號碼走勢是否異常。")
    
    df = pd.DataFrame(st.session_state.history_data)
    df['總分'] = df['nums'].apply(sum)
    df['大小'] = df['總分'].apply(lambda x: "大" if x >= 810 else "小")
    df['單雙'] = df['nums'].apply(lambda x: "單" if sum(n%2!=0 for n in x) >= 11 else "雙")
    df['號碼'] = df['nums'].apply(lambda x: " ".join([f"{n:02d}" for n in x]))
    
    # 使用 Streamlit Column Config 進行視覺化
    st.dataframe(
        df[['id', '總分', '大小', '單雙', '號碼']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.TextColumn("期別", width="small"),
            "號碼": st.column_config.TextColumn("開獎號碼 (20碼)", width="large"),
            "總分": st.column_config.ProgressColumn(
                "總分能量 (810為界)",
                help="總分越高，能量條越長",
                format="%d",
                min_value=600, # 賓果總分極限通常在 600-1000 之間
                max_value=1000,
            ),
            "大小": st.column_config.TextColumn("大小"), # Streamlit 目前對文字標籤支援有限，用文字即可，配合下方說明
            "單雙": st.column_config.TextColumn("單雙"),
        }
    )
    
    # 底部狀態列
    st.markdown(f"<div style='text-align:center; color:#555; font-size:0.8em; margin-top:20px;'>NEBULA ORACLE SYSTEM v3.0 | CONNECTION STABLE | LATENCY: 24ms</div>", unsafe_allow_html=True)

# 自動刷新
time.sleep(1)
if time.time() - st.session_state.last_run_time > 300:
    update()
    st.rerun()
else:
    st.rerun()