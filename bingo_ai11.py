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
import random

# 1. 系統設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="數位雙生4倍獲利版", page_icon="💎", layout="wide")

# CSS: 鑽石藍風格 (Diamond Blue)
st.markdown("""
    <style>
    .stApp { background-color: #000000; color: #00f2ff; font-family: 'Segoe UI', sans-serif; }
    
    .twin-header {
        text-align: center;
        font-size: 3em;
        font-weight: 900;
        background: linear-gradient(to right, #00f2ff, #ffffff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0 0 20px rgba(0, 242, 255, 0.5);
        margin-bottom: 20px;
    }

    .sim-box {
        border: 1px solid #00f2ff;
        background: rgba(0, 242, 255, 0.05);
        padding: 15px;
        color: #fff;
        font-family: monospace;
        margin-bottom: 20px;
        border-radius: 5px;
        text-align: center;
    }

    .twin-ball {
        width: 140px;
        height: 140px;
        line-height: 140px;
        border-radius: 50%;
        text-align: center;
        font-size: 4em;
        font-weight: 900;
        color: #000;
        background: radial-gradient(circle at 30% 30%, #ffffff, #00f2ff);
        box-shadow: 0 0 40px #00f2ff, inset 0 0 20px #fff;
        border: 4px solid #fff;
        margin: 0 auto;
        animation: float 4s ease-in-out infinite;
    }
    
    @keyframes float {
        0% { transform: translateY(0px); box-shadow: 0 0 30px #00f2ff; }
        50% { transform: translateY(-10px); box-shadow: 0 0 60px #00f2ff; }
        100% { transform: translateY(0px); box-shadow: 0 0 30px #00f2ff; }
    }
    
    .prob-tag {
        text-align: center;
        margin-top: 15px;
        background: #001133;
        border: 1px solid #00f2ff;
        color: #00f2ff;
        padding: 5px;
        border-radius: 10px;
        font-weight: bold;
    }

    /* 策略卡片 */
    .strategy-card {
        background: #0a1929;
        border: 2px solid #333;
        border-radius: 15px;
        padding: 20px;
        margin-bottom: 20px;
        height: 100%;
        position: relative;
        transition: all 0.3s;
    }
    
    .strategy-winner {
        border-color: #00f2ff;
        box-shadow: 0 0 20px rgba(0, 242, 255, 0.2);
        background: rgba(0, 242, 255, 0.05);
    }

    .card-title {
        font-size: 1.5em; 
        font-weight: bold; 
        text-align: center; 
        margin-bottom: 15px;
        border-bottom: 1px solid #555;
        padding-bottom: 10px;
    }
    
    .profit-text {
        font-size: 1.2em;
        font-weight: bold;
        color: #00ff00;
    }
    
    .loss-text {
        font-size: 1.2em;
        font-weight: bold;
        color: #ff3333;
    }

    @media (max-width: 768px) {
        .twin-header { font-size: 2em; }
        .twin-ball { width: 100px; height: 100px; line-height: 100px; font-size: 3em; }
    }
    
    div[data-testid="stDataFrame"] { background: #001133; border: 1px solid #003366; }
    </style>
""", unsafe_allow_html=True)

# Session State
if 'history_data' not in st.session_state: st.session_state.history_data = []
if 'final_result' not in st.session_state: st.session_state.final_result = None
if 'data_status' not in st.session_state: st.session_state.data_status = "Waiting..."

# --- 1. 核心抓取 (含備援) ---
def generate_mock_data():
    mock_data = []
    base_id = 115008000
    for i in range(80):
        draw = sorted(random.sample(range(1, 81), 20))
        mock_data.append({"id": str(base_id - i), "nums": draw})
    return mock_data

def fetch_data():
    url = "https://www.pilio.idv.tw/bingo/list.asp"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5, verify=False)
        res.encoding = 'big5'
        if res.status_code != 200: 
            return generate_mock_data(), "⚠️ 離線模擬 (連線失敗)"
        
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.find_all('tr')
        results = []
        seen_ids = set()
        for row in rows:
            text = row.get_text(strip=True)
            id_match = re.search(r'(11[5-6]\d{6})', text)
            if id_match:
                draw_id = id_match.group(1)
                if draw_id in seen_ids: continue
                nums = re.findall(r'\d+', text)
                clean_nums = []
                for n in nums:
                    val = int(n)
                    if str(val) == draw_id: continue
                    if 1 <= val <= 80 and val not in clean_nums: clean_nums.append(val)
                if len(clean_nums) >= 20:
                    ball_20 = sorted(clean_nums[:20])
                    results.append({"id": draw_id, "nums": ball_20})
                    seen_ids.add(draw_id)
        
        if len(results) < 10: return generate_mock_data(), "⚠️ 離線模擬 (資料不足)"
        return results[:80], "✅ 連線正常 (Live Data)"
    except:
        return generate_mock_data(), "⚠️ 離線模擬 (網路異常)"

# --- 2. 數位雙生演算法 ---
def run_algorithm(data):
    try: latest_id = int(data[0]['id'])
    except: latest_id = 12345
    np.random.seed(latest_id)
    
    all_nums = [n for d in data for n in d['nums']]
    counts = Counter(all_nums)
    last_draw = data[0]['nums']
    
    # 共現矩陣
    co_matrix = np.zeros((81, 81))
    for draw in data:
        nums = draw['nums']
        for i in range(len(nums)):
            for j in range(i+1, len(nums)):
                co_matrix[nums[i]][nums[j]] += 1
                co_matrix[nums[j]][nums[i]] += 1

    scores = {n: 0.0 for n in range(1, 81)}
    for n in range(1, 81):
        scores[n] += counts[n] * 3.0
        gravity = 0
        if (n-1) in last_draw: gravity += 10
        if (n+1) in last_draw: gravity += 10
        for prev in last_draw: gravity += co_matrix[prev][n] * 0.2
        scores[n] += gravity
        curr_gap = 0
        for i, draw in enumerate(data):
            if n in draw['nums']:
                curr_gap = i
                break
            curr_gap = i + 1
        avg_gap = 80 / (counts[n] if counts[n] > 0 else 1)
        if curr_gap > avg_gap: scores[n] += 15
        scores[n] += np.random.uniform(0, 5)

    top_3 = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:3]
    
    # 3D 數據
    features = []
    for n in range(1, 81):
        features.append({
            "num": n, "freq": counts[n], 
            "gap": next((i for i, d in enumerate(data) if n in d['nums']), len(data)),
            "score": scores[n], "is_top": n in top_3
        })
    df_feat = pd.DataFrame(features)
    probs = {n: int(min(99, (scores[n]/scores[top_3[0]])*95)) for n in top_3}
    
    return {"top_3": top_3, "df_feat": df_feat, "probs": probs}

# --- 3. 更新與 UI ---
def update():
    data, status = fetch_data()
    st.session_state.data_status = status
    if data:
        st.session_state.history_data = data
        res = run_algorithm(data)
        if res:
            st.session_state.final_result = res
        return True
    return False

# 自動執行檢查
if st.session_state.final_result is None or st.session_state.data_status == "Waiting...":
    update()

# --- 介面呈現 ---
st.markdown("<div class='twin-header'>DIGITAL TWIN: 4X STRATEGY</div>", unsafe_allow_html=True)

# 側邊欄
with st.sidebar:
    st.markdown("### 💠 系統狀態")
    st.code(st.session_state.data_status)
    if st.button("🔄 強制重刷", type="primary"):
        update()
        st.rerun()

if st.session_state.final_result:
    res = st.session_state.final_result
    top_3 = res['top_3']
    probs = res['probs']
    df_feat = res['df_feat']
    latest_id = st.session_state.history_data[0]['id']
    
    # HUD
    st.markdown(f"""
    <div class='sim-box'>
        > <b>目標期別</b>：{int(latest_id)+1} ~ {int(latest_id)+10} 期 (10期波段)<br>
        > <b>推薦策略</b>：<span style='color:#00f2ff'>4倍三星重注 (4x 3-Star)</span><br>
        > <b>鎖定號碼</b>：{top_3}
    </div>
    """, unsafe_allow_html=True)

    # 核心球體
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f"<div class='twin-ball'>{top_3[0]:02d}</div><div class='prob-tag'>AI 信心度 {probs[top_3[0]]}%</div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='twin-ball'>{top_3[1]:02d}</div><div class='prob-tag'>AI 信心度 {probs[top_3[1]]}%</div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='twin-ball'>{top_3[2]:02d}</div><div class='prob-tag'>AI 信心度 {probs[top_3[2]]}%</div>", unsafe_allow_html=True)

    # 3D 空間
    with st.expander("🌌 查看 3D 號碼能量分佈 (點擊展開)"):
        fig = go.Figure(data=[go.Scatter3d(
            x=df_feat['freq'], y=df_feat['gap'], z=df_feat['score'],
            mode='markers+text',
            marker=dict(
                size=[15 if x else 5 for x in df_feat['is_top']],
                color=['#ff0000' if x else '#00f2ff' for x in df_feat['is_top']],
                opacity=0.8
            ),
            text=[str(n) if t else "" for n, t in zip(df_feat['num'], df_feat['is_top'])],
            textfont=dict(color='white', size=15)
        )])
        fig.update_layout(scene = dict(xaxis_title='熱度', yaxis_title='遺漏', zaxis_title='能量', xaxis=dict(backgroundcolor="black"), yaxis=dict(backgroundcolor="black"), zaxis=dict(backgroundcolor="black")), paper_bgcolor='black', height=400, margin=dict(l=0,r=0,b=0,t=0))
        st.plotly_chart(fig, use_container_width=True)

    # 💰 策略比較 (修正後的正確數學)
    st.markdown("---")
    st.subheader("💰 10期波段策略分析 (The Mathematical Winner)")
    
    col_strat_a, col_strat_b = st.columns(2)
    
    # 策略數據
    # 方案 A: 3星x4注 (成本100)
    # 中2碼: 50 * 4 = 200 (賺100)
    # 中3碼: 500 * 4 = 2000 (賺1900)
    
    # 方案 B: 3星x1注 + 2星x3注 (成本100)
    # 中2碼: 50(3星) + 75(2星) = 125 (賺25)
    # 中3碼: 500(3星) + 225(2星) = 725 (賺625)

    with col_strat_a:
        st.markdown(f"""
        <div class='strategy-card strategy-winner'>
            <div class='card-title' style='color:#00f2ff;'>🏆 方案 A：4倍三星 (絕對優勢)</div>
            <p>每期買 4 注三星 (成本 $100)。</p>
            <ul>
                <li><b>中 2 碼</b>：領 $200 <span class='profit-text'>(淨利 +100)</span></li>
                <li><b>中 3 碼</b>：領 $2,000 <span class='profit-text'>(淨利 +1,900)</span></li>
            </ul>
            <p style='color:#00f2ff; font-weight:bold;'>
                AI 結論：完勝。因為三星中2碼有獎金 ($50)，買 4 倍放大後，連「防禦力」都比方案 B 強！
            </p>
        </div>
        """, unsafe_allow_html=True)
        
    with col_strat_b:
        st.markdown(f"""
        <div class='strategy-card'>
            <div class='card-title' style='color:#888;'>方案 B：二星混買 (已過時)</div>
            <p>1 注三星 + 3 注二星 (成本 $100)。</p>
            <ul>
                <li><b>中 2 碼</b>：領 $125 <span class='profit-text'>(淨利 +25)</span></li>
                <li><b>中 3 碼</b>：領 $725 <span class='profit-text'>(淨利 +625)</span></li>
            </ul>
            <p style='color:#888;'>
                缺點：混買二星反而稀釋了獲利。既然三星本身就保本，不需要再買二星來避險。
            </p>
        </div>
        """, unsafe_allow_html=True)

    # 獲利比較圖
    fig_roi = go.Figure()
    fig_roi.add_trace(go.Bar(
        x=['中2碼 (防禦)', '中3碼 (進攻)'],
        y=[200, 2000],
        name='方案 A (4倍三星)',
        marker_color='#00f2ff',
        text=['$200', '$2000'],
        textposition='auto'
    ))
    fig_roi.add_trace(go.Bar(
        x=['中2碼 (防禦)', '中3碼 (進攻)'],
        y=[125, 725],
        name='方案 B (混買)',
        marker_color='#555',
        text=['$125', '$725'],
        textposition='auto'
    ))
    fig_roi.update_layout(
        title="單期獲利能力比較 (同樣成本 $100)",
        plot_bgcolor='#111',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white'),
        yaxis_title="獎金 (元)",
        barmode='group'
    )
    st.plotly_chart(fig_roi, use_container_width=True)

    # 歷史表格
    st.markdown("---")
    df = pd.DataFrame(st.session_state.history_data)
    df['總分'] = df['nums'].apply(sum)
    df['號碼'] = df['nums'].apply(lambda x: " ".join([f"{n:02d}" for n in x]))
    st.dataframe(df[['id', '總分', '號碼']], use_container_width=True, hide_index=True)

else:
    st.info("系統正在啟動中，請稍候...")