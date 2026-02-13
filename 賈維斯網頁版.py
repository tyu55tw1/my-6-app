import streamlit as st
import requests
import random
import re
import itertools
import urllib3
import time
import urllib.parse
import google.generativeai as genai
from collections import Counter
from bs4 import BeautifulSoup

# 1. 基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 嘗試匯入 BeautifulSoup
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ==========================================
# 🔑 API 金鑰設定區
# ==========================================
GEMINI_API_KEY = "AIzaSyACLssBFMWfLpIprNmx7TdQe_k4k4JCLEM"
WEATHER_API_KEY = "E3e2c14f7956d939b88a6dfa66e4f10a"

# ==========================================
# 🔍 核心 1: 智能搜尋
# ==========================================
class WebSearcher:
    @staticmethod
    def decode_ddg_url(raw_url):
        try:
            if raw_data := re.search(r'uddg=([^&]+)', raw_url):
                return urllib.parse.unquote(raw_data.group(1))
            return raw_url if raw_url.startswith('http') else ""
        except: return ""

    @staticmethod
    def search_wiki(query):
        try:
            url = "https://zh.wikipedia.org/w/api.php"
            params = {"action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": 3}
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            results = []
            if "query" in data and "search" in data["query"]:
                for item in data["query"]["search"]:
                    title = item["title"]
                    snippet = re.sub(r'<[^>]+>', '', item["snippet"])
                    link = f"https://zh.wikipedia.org/wiki/{title}"
                    results.append({"title": f"📚 [維基] {title}", "link": link, "snippet": snippet})
            return results
        except: return []

    @staticmethod
    def search_advanced(query, model):
        try:
            url = f"https://html.duckduckgo.com/html/?q={query}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            results_list = []
            snippets_text = []

            # Wiki
            wiki_res = WebSearcher.search_wiki(query)
            results_list.extend(wiki_res)
            for w in wiki_res: snippets_text.append(f"{w['title']}: {w['snippet']}")

            # DDG
            for i, result in enumerate(soup.find_all('div', class_='result'), 1):
                if i > 8: break 
                title_tag = result.find('a', class_='result__a')
                snippet_tag = result.find('a', class_='result__snippet')
                
                if title_tag:
                    title = title_tag.get_text().strip()
                    raw_link = title_tag['href']
                    real_link = WebSearcher.decode_ddg_url(raw_link)
                    snippet = snippet_tag.get_text().strip() if snippet_tag else ""
                    
                    if real_link:
                        results_list.append({"title": title, "link": real_link, "snippet": snippet})
                        snippets_text.append(f"標題：{title}\n摘要：{snippet}")

            # AI 總結
            raw_data = "\n\n".join(snippets_text[:6])
            ai_summary = "❌ 搜尋無結果。"
            
            if raw_data:
                if model:
                    prompt = f"請根據以下資料回答：『{query}』\n資料：{raw_data}\n請直接給出重點答案（日期、數字），不要列出網址。"
                    try:
                        ai_resp = model.generate_content(prompt)
                        ai_summary = ai_resp.text
                    except:
                        ai_summary = f"**搜尋摘要 (AI 忙線)**：\n{raw_data[:500]}..."
                else:
                    ai_summary = f"**搜尋摘要**：\n{raw_data[:500]}..."
            
            return ai_summary, results_list
        except Exception as e: return f"⚠️ 搜尋錯誤: {e}", []

# ==========================================
# 🎰 核心 2: 賓果/樂透 (1代算法)
# ==========================================
class LottoAlgorithm:
    @staticmethod
    def calculate_ac(numbers):
        r = len(numbers)
        diffs = set()
        for pair in itertools.combinations(numbers, 2): diffs.add(abs(pair[0] - pair[1]))
        return len(diffs) - (r - 1)
    @staticmethod
    def is_prime(n):
        if n < 2: return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0: return False
        return True
    @staticmethod
    def predict(l_type):
        if "大樂透" in l_type or "大熱透" in l_type: max_n, pick, min_ac = 49, 6, 7
        elif "威力" in l_type: max_n, pick, min_ac = 38, 6, 7
        elif "539" in l_type: max_n, pick, min_ac = 39, 5, 4
        else: return "⚠️ 未知彩種", []

        primes = [n for n in range(1, max_n+1) if LottoAlgorithm.is_prime(n)]
        best_combo = None
        for _ in range(5000):
            combo = sorted(random.sample(range(1, max_n+1), pick))
            if LottoAlgorithm.calculate_ac(combo) < min_ac: continue
            p_cnt = sum(1 for n in combo if n in primes)
            if not (1 <= p_cnt <= 3): continue
            best_combo = combo
            break
        if not best_combo: best_combo = sorted(random.sample(range(1, max_n+1), pick))
        
        special = f" + 第二區 [{random.randint(1,8):02d}]" if "威力" in l_type else ""
        return f"🎰 **{l_type.replace('熱','樂')} 預測**\n\n🔢 **{best_combo}** {special}\n\n📊 AC值：{LottoAlgorithm.calculate_ac(best_combo)}", []

class BingoAlgorithm:
    @staticmethod
    def analyze_and_predict(stars=5):
        if not HAS_BS4: return "⚠️ 請先安裝 bs4", []
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            url = "https://www.pilio.idv.tw/bingo/list.asp"
            res = requests.get(url, headers=headers, timeout=10, verify=False)
            res.encoding = 'big5'
            soup = BeautifulSoup(res.text, 'html.parser')
            all_numbers = []
            for row in soup.find_all('tr'):
                text = row.get_text(strip=True)
                if re.search(r'11[3-9]\d{6}', text) or re.search(r'11[0-2]\d{6}', text): 
                    nums = [int(n) for n in re.findall(r'\d+', text) if int(n) <= 80][:20]
                    if len(nums) == 20: all_numbers.extend(nums)
            
            if not all_numbers: return "❌ 賓果網站阻擋", []
            counts = Counter(all_numbers)
            hot_numbers = counts.most_common(stars)
            prediction = sorted([num for num, count in hot_numbers])
            return f"🎱 **賓果 {stars} 星預測 (追熱)**\n\n🔥 推薦：**{prediction}**", []
        except Exception as e: return f"⚠️ 賓果錯誤: {e}", []

    @staticmethod
    def get_latest():
        return "📢 請查看右側搜尋面板", []

# ==========================================
# 📈 核心 3: 財經/天氣
# ==========================================
class DirectInfo:
    @staticmethod
    def get_stock(code):
        try:
            ts = int(time.time() * 1000)
            url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw|otc_{code}.tw&json=1&_={ts}"
            res = requests.get(url, timeout=5, verify=False)
            data = res.json()
            if 'msgArray' in data and data['msgArray']:
                i = data['msgArray'][0]
                p = i.get('z', '-')
                if p == '-': p = i.get('b', '-').split('_')[0]
                diff_val = float(p) - float(i.get('y', 0)) if p != '-' and i.get('y') != '-' else 0
                color = "red" if diff_val > 0 else "green" if diff_val < 0 else "grey"
                return f"📈 **台股 {code} {i.get('n',code)}**\n\n💰 現價：**{p}**\n📊 昨收：{i.get('y','-')}\n🔥 漲跌：:{color}[{diff_val:.2f}]", []
            return "⚠️ 查無代碼", []
        except: return "⚠️ 股價忙線", []

    @staticmethod
    def get_weather(city):
        try:
            city_map = {"台北": "Taipei", "台南": "Tainan", "台中": "Taichung", "高雄": "Kaohsiung"}
            q = city_map.get(city.replace("台","臺"), city)
            if q == city: q = city_map.get(city.replace("臺","台"), city)
            url = "http://api.openweathermap.org/data/2.5/weather"
            params = {'q': q, 'appid': WEATHER_API_KEY, 'units': 'metric', 'lang': 'zh_tw'}
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                d = r.json()
                return f"📍 **{d['name']}**\n\n🌡️ {d['main']['temp']}°C\n☁️ {d['weather'][0]['description']}", []
            return "❌ 查無城市", []
        except: return "⚠️ 天氣錯誤", []

# ==========================================
# 🧠 賈維斯大腦 (邏輯修復)
# ==========================================
def get_ai_model():
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        avail = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target = 'gemini-1.5-flash' if 'models/gemini-1.5-flash' in avail else 'gemini-pro'
        return genai.GenerativeModel(target), target
    except:
        return None, "離線"

def jarvis_think(text, model):
    raw = text
    text = text.lower()
    
    # 🟢 修正：加入中文數字對照表
    cn_num = {'一':1, '二':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '十':10}

    # 1. 賓果/樂透
    if "預測" in text or "算牌" in text or "賓果" in text:
        if "大樂透" in text or "大熱透" in text: return LottoAlgorithm.predict("大樂透")
        if "威力" in text: return LottoAlgorithm.predict("威力彩")
        if "539" in text: return LottoAlgorithm.predict("539")
        
        # 預設 5 星
        stars = 5
        
        # 🟢 邏輯 1: 檢查中文數字 (一星~十星)
        for k, v in cn_num.items(): 
            if f"{k}星" in text or f"{k} 星" in text: 
                stars = v
                break
        
        # 🟢 邏輯 2: 檢查阿拉伯數字 (優先權較高，覆蓋中文)
        m = re.search(r'(\d+)\s*星', text)
        if m: stars = int(m.group(1))
        
        return BingoAlgorithm.analyze_and_predict(stars)

    # 2. 股價/天氣
    if "股" in text and re.search(r'\d{4,6}', text):
        return DirectInfo.get_stock(re.search(r'\d{4,6}', text).group(0))
    if "天氣" in text:
        return DirectInfo.get_weather(text.replace("天氣","").strip() or "台南")

    # 3. 智能搜尋
    search_triggers = ["時間", "日期", "新聞", "報名", "報考", "幾點", "什麼時候", "是誰", "多少錢", "搜尋", "查"]
    if any(k in text for k in search_triggers) or (model and len(text) > 4):
        return WebSearcher.search_advanced(raw, model)

    # 4. 閒聊
    if model:
        try: return model.generate_content(raw).text, []
        except: pass
    
    return "🤖 請輸入明確指令", []

# ==========================================
# 🌐 Streamlit 網頁介面
# ==========================================
st.set_page_config(page_title="Jarvis Web", layout="wide", page_icon="🤖")

if "history" not in st.session_state:
    st.session_state.history = []
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "model" not in st.session_state:
    model, name = get_ai_model()
    st.session_state.model = model
    st.session_state.model_name = name

st.markdown("""
<style>
    .reportview-container { margin-top: -2em; }
    .stDeployButton {display:none;}
    #MainMenu {visibility: hidden;}
    a {text-decoration: none; color: #3498db !important; font-weight: bold;}
    a:hover {text-decoration: underline; color: #63cdda !important;}
    .search-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border: 1px solid #333;
    }
</style>
""", unsafe_allow_html=True)

col_head1, col_head2 = st.columns([8, 2])
with col_head1:
    st.title("🤖 Jarvis Web OS")
with col_head2:
    st.success(f"AI: {st.session_state.model_name}")

col_chat, col_feed = st.columns([7, 3])

with col_chat:
    chat_container = st.container(height=600)
    for msg in st.session_state.history:
        with chat_container.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    if prompt := st.chat_input("輸入指令 (如: 賓果三星 / 2026五專報名 / 00919股價)..."):
        st.session_state.history.append({"role": "user", "content": prompt})
        with chat_container.chat_message("user"):
            st.write(prompt)
            
        with chat_container.chat_message("assistant"):
            with st.spinner("Jarvis 正在運算..."):
                reply, s_results = jarvis_think(prompt, st.session_state.model)
                st.markdown(reply)
                
        st.session_state.history.append({"role": "assistant", "content": reply})
        st.session_state.search_results = s_results
        st.rerun()

with col_feed:
    st.subheader("🌐 即時資訊流")
    if not st.session_state.search_results:
        st.info("尚無外部資訊，請嘗試搜尋相關問題。")
    else:
        for item in st.session_state.search_results:
            st.markdown(f"""
            <div class="search-card">
                <a href="{item['link']}" target="_blank" style="font-size: 16px;">
                    {item['title']}
                </a>
                <p style="color: #bbb; font-size: 13px; margin-top: 5px;">
                    {item['snippet']}
                </p>
            </div>
            """, unsafe_allow_html=True)