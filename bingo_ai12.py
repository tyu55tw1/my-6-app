import streamlit as st
import pandas as pd
import requests
import re
import urllib3
from bs4 import BeautifulSoup

# 1. 系統設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="賓果格子輸入版", page_icon="🔢", layout="wide")

# CSS: 乾淨風格
st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; color: #333; font-family: 'Microsoft JhengHei', sans-serif; }
    
    .header {
        text-align: center;
        font-size: 2.2em;
        font-weight: 900;
        color: #2c3e50;
        border-bottom: 3px solid #3498db;
        padding-bottom: 10px;
        margin-bottom: 20px;
    }

    /* 驗證卡片 */
    .verify-card {
        background: #fff;
        border: 2px solid #3498db;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* 球號樣式 */
    .ball {
        display: inline-block;
        width: 32px;
        height: 32px;
        line-height: 32px;
        border-radius: 50%;
        text-align: center;
        font-weight: bold;
        font-size: 0.9em;
        margin: 2px;
    }
    .ball-verify { background: #2c3e50; color: #fff; }
    .ball-hit { background: #e74c3c; color: white; }
    .ball-miss { background: #ecf0f1; color: #bdc3c7; }

    /* 損益表 */
    .result-row-win {
        background: #e8f5e9;
        border-left: 5px solid #27ae60;
        padding: 10px;
        margin-bottom: 5px;
        border-radius: 4px;
    }
    .result-row-loss {
        background: #fff;
        border-left: 5px solid #ccc;
        padding: 10px;
        margin-bottom: 5px;
        border-radius: 4px;
        color: #888;
    }
    
    /* 輸入框優化 */
    div[data-testid="stTextInput"] input {
        text-align: center;
        font-size: 1.2em;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# --- 1. 抓取數據 (保留之前的穩定邏輯) ---
@st.cache_data(ttl=60)
def fetch_data():
    url = "https://www.pilio.idv.tw/bingo/list.asp"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5, verify=False)
        res.encoding = 'big5'
        
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.find_all('tr')
        
        data = []
        seen = set()
        
        for row in rows:
            text = row.get_text(strip=True)
            id_match = re.search(r'(11[3-9]\d{6})', text)
            
            if id_match:
                draw_id = int(id_match.group(1))
                if draw_id in seen: continue
                
                nums = re.findall(r'\d+', text)
                clean = []
                for n in nums:
                    if int(n) == draw_id: continue
                    if len(n) > 2: continue
                    clean.append(int(n))
                
                if len(clean) >= 20:
                    data.append({
                        "期數": draw_id,
                        "號碼": sorted(clean[:20])
                    })
                    seen.add(draw_id)
        
        # 回傳由新到舊 (驗證用) 和 由舊到新 (下拉選單用)
        df = pd.DataFrame(data).sort_values(by="期數", ascending=False).reset_index(drop=True)
        return df, "✅ 數據已同步"
    except Exception as e:
        return pd.DataFrame(), f"❌ 連線失敗: {e}"

# --- 2. 獎金表 ---
def get_prize(star, hits):
    table = {
        1: {1: 50}, 2: {1: 25, 2: 75}, 3: {2: 50, 3: 500},
        4: {2: 25, 3: 100, 4: 1000}, 5: {3: 50, 4: 500, 5: 7500},
        6: {3: 25, 4: 200, 5: 1000, 6: 25000}, 7: {3: 25, 4: 50, 5: 300, 6: 3000, 7: 80000},
        8: {4: 25, 5: 100, 6: 800, 7: 20000, 8: 500000}, 
        9: {4: 25, 5: 100, 6: 1000, 7: 3000, 8: 100000, 9: 1000000},
        10: {5: 25, 6: 100, 7: 1000, 8: 5000, 9: 25000, 10: 5000000}
    }
    return table.get(star, {}).get(hits, 0)

# --- 3. 介面呈現 ---
st.markdown("<div class='header'>🔢 賓果格子填空回測版</div>", unsafe_allow_html=True)

df, status = fetch_data()

# A. 數據驗證區 (最重要)
if not df.empty:
    latest = df.iloc[0]
    st.markdown(f"""
    <div class='verify-card'>
        <div style='display:flex; justify-content:space-between; align-items:center;'>
            <span style='font-size:1.1em; font-weight:bold; color:#2c3e50;'>📡 資料驗證 ({status})</span>
        </div>
        <div style='margin-top:10px; font-weight:bold;'>最新期數：{latest['期數']}</div>
        <div style='margin-top:5px;'>
            {''.join([f"<span class='ball ball-verify'>{n:02d}</span>" for n in latest['號碼']])}
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.error("無法連線至資料來源。")
    st.stop()

# B. 側邊欄：格子輸入法
with st.sidebar:
    st.header("⚙️ 填寫號碼")
    
    # 1. 選擇幾星
    star = st.selectbox("玩法 (幾星就幾個格子)", range(1, 11), index=2, format_func=lambda x: f"{x} 星")
    
    # 2. 動態生成格子
    st.write(f"👇 請填入 {star} 個號碼：")
    
    input_nums = []
    # 使用 3 列排版，避免格子太小或太長
    cols = st.columns(3) 
    
    for i in range(star):
        with cols[i % 3]:
            # key 確保每個格子獨立
            val = st.text_input(f"球{i+1}", key=f"ball_{i}", max_chars=2, placeholder="00")
            if val.strip().isdigit():
                input_nums.append(int(val))
            else:
                input_nums.append(None) # 未填或填錯
    
    # 3. 倍數
    st.markdown("---")
    mult = st.number_input("倍數 (每注$25)", 1, 100, 1)

    # 4. 期數選擇 (下拉選單)
    st.markdown("---")
    st.write("📅 選擇回測範圍 (下拉選單)")
    
    # 為了選單是由小到大 (舊->新)，我們重新排序一下 list
    all_periods = sorted(df['期數'].tolist())
    
    idx_start = max(0, len(all_periods) - 20)
    p_start = st.selectbox("起始期數", all_periods, index=idx_start)
    p_end = st.selectbox("結束期數", all_periods, index=len(all_periods)-1)
    
    run_btn = st.button("🚀 計算損益", type="primary")

# C. 計算邏輯
if run_btn:
    # 資料清洗與檢查
    clean_nums = [n for n in input_nums if n is not None]
    
    # 檢查1: 是否有空值
    if len(clean_nums) < star:
        st.error(f"❌ 還有格子沒填！請填滿 {star} 個號碼。")
    # 檢查2: 是否有重複
    elif len(set(clean_nums)) != len(clean_nums):
        st.error("❌ 號碼不能重複！請檢查格子。")
    # 檢查3: 範圍
    elif any(n < 1 or n > 80 for n in clean_nums):
        st.error("❌ 號碼必須在 01 ~ 80 之間。")
    # 檢查4: 期數
    elif p_start > p_end:
        st.error("❌ 起始期數不能大於結束期數。")
    else:
        # 開始計算
        my_nums = sorted(clean_nums)
        
        mask = (df['期數'] >= p_start) & (df['期數'] <= p_end)
        # 這裡為了顯示習慣 (新->舊)，我們用原始 df (已經是 sort by desc)
        # 但要注意 mask 篩選
        target = df.loc[mask] 
        
        total_cost = len(target) * 25 * mult
        total_win = 0
        
        history_html = ""
        
        for _, row in target.iterrows():
            d_nums = set(row['號碼'])
            m_set = set(my_nums)
            hits = len(m_set.intersection(d_nums))
            
            prize = get_prize(star, hits) * mult
            total_win += prize
            
            # 產生顯示
            ball_html = ""
            for n in my_nums:
                style = "ball-hit" if n in d_nums else "ball-miss"
                ball_html += f"<span class='ball {style}'>{n:02d}</span>"
            
            row_cls = "result-row-win" if prize > 0 else "result-row-loss"
            prize_str = f"<b style='color:#d32f2f'>+${prize}</b>" if prize > 0 else "<span style='color:#aaa'>-25</span>"
            
            history_html += f"""
            <div class='{row_cls}'>
                <div style='display:flex; justify-content:space-between;'>
                    <b>第 {row['期數']} 期</b>
                    {prize_str}
                </div>
                <div style='margin-top:5px'>{ball_html}</div>
            </div>
            """
            
        net = total_win - total_cost
        
        st.subheader("📊 損益報告")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("期數", len(target))
        c2.metric("成本", f"${total_cost}")
        c3.metric("獎金", f"${total_win}")
        c4.metric("淨利", f"${net}", delta_color="normal" if net==0 else "inverse")
        
        st.markdown(history_html, unsafe_allow_html=True)

elif not df.empty:
    st.info(f"👈 請在左側填入 {star} 個號碼，系統會自動幫您對獎！")