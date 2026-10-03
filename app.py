# -*- coding: utf-8 -*-
"""🧰 全方位生活助手 — Streamlit 版。  執行:streamlit run app.py"""
import io
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import streamlit as st

import core as K

st.set_page_config(page_title="全方位生活助手", page_icon="🧰", layout="wide", initial_sidebar_state="auto")
st.markdown("""<style>
.block-container{padding-top:1.4rem;max-width:1100px}
.hero{background:linear-gradient(135deg,#ff6b3d,#ff9a5c 55%,#f5c542);padding:18px 22px;border-radius:20px;margin-bottom:14px;color:#fff}
.hero h1{margin:0;font-size:1.7rem;color:#fff}.hero p{margin:2px 0 0;opacity:.92}
.chip{display:inline-block;padding:3px 11px;margin:2px 4px 2px 0;border-radius:9px;background:#2a3241;font-weight:700;font-size:.92rem}
.chip.past{background:#171b23;color:#556073}.chip.next{background:#ff6b3d;color:#fff}
.badge{display:inline-block;padding:1px 9px;border-radius:7px;color:#fff;font-size:.78rem;font-weight:700;margin-right:6px}
.ball{display:inline-grid;place-items:center;width:38px;height:38px;border-radius:50%;background:#ff6b3d;color:#fff;font-weight:700;margin:3px}
.ball.z{background:#4aa3ff}.big{font-size:2.4rem;font-weight:800;line-height:1.1}
div[data-testid=stMetric]{background:#1a1f2b;border:1px solid #2a3242;border-radius:16px;padding:12px 16px}
@media(max-width:640px){.hero h1{font-size:1.3rem}.big{font-size:1.9rem}.ball{width:32px;height:32px}}
</style>""", unsafe_allow_html=True)

PAGES = ["🎬 電影時刻", "⛅ 天氣", "⛽ 油價", "📈 股票", "💱 匯率", "🧾 發票對獎", "🎰 賓果", "🏆 樂透", "🤖 AI 下注顧問", "📸 大頭照", "🔧 連線診斷"]
page = st.sidebar.radio("功能", PAGES, label_visibility="collapsed")
st.sidebar.caption("資料來源:開眼電影網・wttr.in・台灣中油・證交所・財政部・pilio")


def hero(title, sub=""):
    st.markdown(f"<div class='hero'><h1>{title}</h1><p>{sub}</p></div>", unsafe_allow_html=True)


def balls(nums, z=None):
    h = "".join(f"<span class='ball'>{n:02d}</span>" for n in nums)
    return h + (f"<b> + </b><span class='ball z'>{z:02d}</span>" if z else "")


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        st.error(f"連線失敗:{type(e).__name__}:{e}")
        return None


# ── 快取包裝(避免重複請求外部網站) ──
@st.cache_resource
def mclient():
    return K.MovieClient(ttl=300)


@st.cache_data(ttl=300, show_spinner="讀取戲院清單…")
def cinemas(code):
    return mclient().list_cinemas(code)


@st.cache_data(ttl=300, show_spinner="讀取場次…")
def schedule(cid, area, name):
    return mclient().get_schedule(K.Cinema(cid, area, name))


@st.cache_data(ttl=300, show_spinner="掃描各戲院場次(第一次約需數秒)…")
def scan(code):
    cs = cinemas(code)

    def one(c):
        try:
            return c.cid, schedule(c.cid, c.area, c.name)
        except Exception:  # noqa: BLE001
            return c.cid, None

    with ThreadPoolExecutor(6) as ex:
        return {cid: s for cid, s in ex.map(one, cs) if s}


weather = st.cache_data(ttl=600, show_spinner="取得氣象…")(K.fetch_weather)
oil = st.cache_data(ttl=1800, show_spinner="取得牌價…")(K.fetch_oil)
stock = st.cache_data(ttl=20, show_spinner="取得報價…")(K.fetch_stock)
rates = st.cache_data(ttl=1800, show_spinner="取得匯率…")(K.fetch_rates)
invoices = st.cache_data(ttl=3600, show_spinner="取得財政部號碼…")(K.fetch_invoice_periods)
bingo_draws = st.cache_data(ttl=300, show_spinner="取得賓果開獎…")(K.fetch_bingo)


def show_sessions(sessions, day):
    now, first = datetime.now(), True
    for s in sessions:
        h = f"<b style='color:#ff9a5c'>{s.label}</b><br>" if s.label else ""
        for t in s.times:
            past = K.is_past(day, t, now)
            cls = "past" if past else ("next" if first and day == now.strftime("%Y/%m/%d") else "")
            first = first and (past or cls == "")
            h += f"<span class='chip {cls}'>{t}</span>"
        st.markdown(h, unsafe_allow_html=True)


def film_card(title, rating, dur, poster, url, body):
    c1, c2 = st.columns([1, 4])
    if poster:
        c1.image(poster)
    name, col = K.RATINGS.get(rating, ("", "#444"))
    c2.markdown(f"**[{title}]({url})**  " + (f"<span class='badge' style='background:{col}'>{name}</span>" if name else "")
                + (f"⏱ {dur} 分" if dur else ""), unsafe_allow_html=True)
    with c2:
        body()


# ═════════ 各頁 ═════════
if page == PAGES[0]:
    hero("🎬 電影時刻", "全台戲院今日場次,已開演的場次自動變暗,橘色為下一場")
    c1, c2 = st.columns(2)
    region = c1.selectbox("地區", list(K.REGIONS))
    mode = c2.radio("查詢方式", ["依戲院", "依電影"], horizontal=True)
    cs = safe(cinemas, K.REGIONS[region])
    if cs:
        if mode == "依戲院":
            c = next(x for x in cs if x.name == st.selectbox("戲院", [x.name for x in cs]))
            sch = safe(schedule, c.cid, c.area, c.name)
            if sch:
                st.caption(f"{c.address}  {c.phone}  ・ 網站更新:{sch.updated or '—'}")
                if not sch.days:
                    st.info("這間戲院目前沒有場次資料")
                else:
                    labels = {d.short: d for d in sch.days}
                    day = labels[st.radio("日期", list(labels), horizontal=True)]
                    for sh in day.shows:
                        with st.container(border=True):
                            film_card(sh.title, sh.rating, sh.duration, sh.poster, sh.url,
                                      lambda sh=sh, d=day: show_sessions(sh.sessions, d.key))
        else:
            res = safe(scan, K.REGIONS[region])
            if res:
                idx = K.build_index({c.cid: res[c.cid] for c in cs if c.cid in res})
                films = sorted(idx.values(), key=lambda f: (-len(f.by_cinema), f.title))
                f = next(x for x in films if f"{x.title}({len(x.by_cinema)}間)" == st.selectbox(
                    "電影", [f"{x.title}({len(x.by_cinema)}間)" for x in films]))
                days = sorted({d for m in f.by_cinema.values() for d in m})
                day = st.radio("日期", days, horizontal=True)
                cmap = {c.cid: c for c in cs}
                for cid, m in f.by_cinema.items():
                    if day in m and cid in cmap:
                        with st.container(border=True):
                            st.markdown(f"**{cmap[cid].name}**")
                            show_sessions(m[day], day)

elif page == PAGES[1]:
    hero("⛅ 天氣", "目前天氣、體感、未來三天與穿衣建議")
    cities = {"台北": "Taipei", "新北": "New Taipei", "桃園": "Taoyuan", "台中": "Taichung", "台南": "Tainan",
              "高雄": "Kaohsiung", "新竹": "Hsinchu", "花蓮": "Hualien", "其他(自行輸入)": ""}
    pick = st.selectbox("城市", list(cities))
    q = st.text_input("城市英文名", "Tokyo") if not cities[pick] else cities[pick]
    d = safe(weather, q)
    if d:
        st.subheader(f"{d['icon']} {d['area'] or q} · {d['desc']}")
        a, b, c, e = st.columns(4)
        a.metric("氣溫", f"{d['temp']}°C"); b.metric("體感", f"{d['feel']}°C")
        c.metric("今日降雨機率", f"{d['rain']}%"); e.metric("濕度", f"{d['humid']}%")
        st.info(K.clothing_advice(K._to_int(d["feel"]), d["rain"], K._to_int(d["uv"])))
        for col, day in zip(st.columns(max(len(d["days"]), 1)), d["days"]):
            col.metric(f"{day['icon']} {day['label']}", f"{day['lo']}° ~ {day['hi']}°", f"☔ {day['rain']}%", delta_color="off")

elif page == PAGES[2]:
    hero("⛽ 油價", "台灣中油最新牌價與加油試算")
    d = safe(oil)
    if d:
        st.caption(f"牌價日期 {d['date']} ・ {d['src']}")
        for col, name, p, pv in zip(st.columns(4), K.OIL_NAMES, d["prices"], d["prev"] or [None] * 4):
            col.metric(name, f"{p:.1f}", f"{p - pv:+.1f}" if pv else None, delta_color="inverse")
        lit = st.number_input("加油量(公升)", 1.0, 200.0, 30.0)
        st.success("  |  ".join(f"{n.split()[0]}:{lit * p:,.0f} 元" for n, p in zip(K.OIL_NAMES, d["prices"])))

elif page == PAGES[3]:
    hero("📈 股票", "收盤價以臺灣證券交易所為準(即時 + 日成交),Yahoo 僅備援")
    c1, c2 = st.columns([1, 2])
    code = c1.text_input("股票代號", "0050")
    rng = c2.radio("區間", list(K.STOCK_RANGES), horizontal=True, index=1)
    d = safe(stock, code, K.STOCK_RANGES[rng])
    if d:
        diff = d["price"] - d["prev"]
        st.subheader(f"{d['code']} {d['name']}")
        a, b, c, e = st.columns(4)
        a.metric("成交 / 收盤", f"{d['price']:,.2f}", f"{diff:+.2f} ({diff / d['prev'] * 100:+.2f}%)" if d["prev"] else None, delta_color="inverse")
        b.metric("今日高 / 低", f"{d['high'] or '--'} / {d['low'] or '--'}")
        c.metric("成交量(張)", f"{d['volume']:,.0f}" if d["volume"] else "--")
        e.metric("昨收", f"{d['prev']:,.2f}")
        st.caption(f"資料來源:{d['src']} ・ 資料時間 {d['asof'] or '—'}")
        if len(d["values"]) > 1:
            st.line_chart(pd.DataFrame({"收盤價": d["values"]}, index=d["labels"]), color="#ff6b3d")

elif page == PAGES[4]:
    hero("💱 匯率", "多幣別即時換算")
    d = safe(rates)
    if d:
        c1, c2 = st.columns(2)
        amt = c1.number_input("金額", 0.0, 1e12, 1000.0)
        base = c2.selectbox("幣別", [f"{c} {n}" for c, _, n in K.FX_CURRENCIES]).split()[0]
        st.caption(f"匯率日期 {d['date']}")
        cols = st.columns(4)
        for i, (code, flag, name) in enumerate(x for x in K.FX_CURRENCIES if x[0] != base):
            v = K.fx_convert(amt, base, code, d["rates"])
            cols[i % 4].metric(f"{flag} {code} {name}", f"{v:,.0f}" if code in ("VND", "KRW") else f"{v:,.2f}",
                               f"1 {base} = {K.fx_convert(1, base, code, d['rates']):,.4f}", delta_color="off")

elif page == PAGES[5]:
    hero("🧾 統一發票對獎", "自動取得財政部最新中獎號碼,免手動輸入")
    ps = safe(invoices)
    if ps:
        p = ps[st.selectbox("期別", range(len(ps)), format_func=lambda i: ps[i]["title"])]
        st.caption(f"領獎期間 {p['claim_start']} ~ {p['claim_end']}" + ("  ⚠️ 已過期" if datetime.now().date().isoformat() > p["claim_end"] else ""))
        a, b = st.columns(2)
        a.metric("特別獎 1,000萬", p["special"][0]); b.metric("特獎 200萬", p["grand"][0])
        st.metric("頭獎 20萬", "   ".join(p["first"]))
        extra = p["extra"] + K.split_numbers(st.text_input("增開六獎(網站未列出時可補,3 碼)", ""), 3)
        txt = st.text_area("輸入發票號碼(每行一張,8 碼或末 3 碼)", height=120)
        toks = [t for t in K.re.split(r"[\s,;、]+", txt.strip()) if K.re.sub(r"\D", "", t)]
        if toks:
            rows = [(K.re.sub(r"\D", "", t), *(lambda r: (("🎉 " if r["ok"] else "") + r["prize"], r["amount"] or "", r["note"]))(
                K.check_invoice(t, p["special"], p["grand"], p["first"], extra))) for t in toks]
            st.dataframe(pd.DataFrame(rows, columns=["號碼", "結果", "獎金", "說明"]), hide_index=True)

elif page == PAGES[6]:
    hero("🎰 賓果", "開獎統計、選號、回測與精確機率(統計無法預測下一期)")
    draws = safe(bingo_draws)
    t1, t2 = st.tabs(["📊 統計與回測", "🧮 機率與期望值"])
    with t1:
        if draws:
            P = st.slider("統計期數", 5, len(draws), min(50, len(draws)))
            fr = K.bingo_freq(draws, P)
            st.bar_chart(pd.DataFrame({"次數": [fr.get(n, 0) for n in range(1, 81)]}, index=[f"{n:02d}" for n in range(1, 81)]), color="#ff6b3d")
            c1, c2 = st.columns(2)
            stars = c1.slider("星數", 1, 10, 3)
            mode = c2.selectbox("選號策略", {"🔥 熱門": "hot", "❄️ 冷門": "cold", "⚖️ 冷熱平衡": "mix", "⏳ 遺漏最久": "omit", "🎲 隨機": "random"}.items(), format_func=lambda x: x[0])[1]
            picks = K.bingo_pick(draws, mode, stars, P)
            st.markdown(balls(picks), unsafe_allow_html=True)
            bt = K.bingo_backtest(draws, picks, min(P, len(draws)))
            a, b, c = st.columns(3)
            a.metric("回測期數", bt["n"]); b.metric("平均命中", f"{bt['avg']:.2f}"); c.metric("亂選的理論平均", f"{bt['expect']:.2f}")
            st.dataframe(pd.DataFrame([(r["期數"], len(r["命中"]), " ".join(f"{n:02d}" for n in r["命中"])) for r in bt["rows"]], columns=["期數", "命中數", "命中號碼"]), hide_index=True)
            u = K.bingo_uniformity(draws)
            if u:
                st.caption(f"🔬 隨機性檢定:χ²={u[0]:.1f},p≈{u[1]:.2f} —— " + ("看不出任何號碼比較容易開出,熱門/冷門只是隨機波動。" if u[1] >= .05 else "p 值偏低,但同時檢驗 80 個號碼偶有低 p 值,對預測下一期仍無幫助。"))
    with t2:
        s = st.slider("星數 ", 1, 10, 9)
        o = K.bingo_odds(s)
        st.metric("總中獎率 / 期望回收率", f"1/{1 / o['win']:.2f}", f"回收率 {o['rtp'] * 100:.1f}%", delta_color="off")
        st.dataframe(pd.DataFrame([(f"中 {r['hits']} 個", K.fmt_prob(r["p"]), f"{r['prize']:,}" if r["prize"] else "—") for r in o["rows"]], columns=["命中", "機率", "獎金(元)"]), hide_index=True)
        st.dataframe(pd.DataFrame([(f"{n} 星", f"1/{1 / K.bingo_odds(n)['win']:.2f}", f"{K.bingo_odds(n)['rtp'] * 100:.1f}%") for n in range(1, 11)], columns=["星數", "總中獎率", "回收率"]), hide_index=True)

elif page == PAGES[7]:
    hero("🏆 樂透選號", "不提高中獎機率;「避開大眾選號」只減少中獎時被分獎")
    c1, c2, c3 = st.columns(3)
    kind = c1.selectbox("彩種", list(K.LOTTO_RULES))
    n = c2.slider("注數", 1, 10, 5)
    mode = c3.selectbox("選號方式", list(K.LOTTO_MODES), format_func=K.LOTTO_MODES.get)
    if st.button("🎲 產生號碼", type="primary"):
        for i, t in enumerate(K.generate_tickets(kind, n, mode=mode), 1):
            st.markdown(f"第 {i} 注 " + balls(t["nums"], random.randint(1, 8) if kind == "威力彩" else None), unsafe_allow_html=True)
    o = K.lotto_odds(kind)
    st.caption(f"每注 {o['price']} 元 ・ 頭獎 1/{1 / o['rows'][0][2]:,.0f} ・ 任一獎約 1/{1 / o['any']:.1f}")
    st.dataframe(pd.DataFrame([(a, b, K.fmt_prob(p)) for a, b, p in o["rows"]], columns=["獎項", "條件", "機率"]), hide_index=True)

elif page == PAGES[8]:
    hero("🤖 AI 下注顧問", "依預算算出最合理的方案與完整勝算(含賓果加倍)")
    c1, c2 = st.columns(2)
    bud = c1.select_slider("預算(元)", [100, 200, 300, 500, 1000, 2000, 5000, 10000], 500)
    goal = c2.selectbox("目標", list(K.GOAL_LABELS), format_func=K.GOAL_LABELS.get)
    c3, c4 = st.columns(2)
    game = c3.selectbox("玩法", ["AI", "賓果", "今彩539", "大樂透", "威力彩"], format_func=lambda x: "AI 幫我選" if x == "AI" else x)
    mult = c4.selectbox("賓果加倍", ["AI", 1, 2, 3, 4, 5, 10, 20, 50], format_func=lambda x: "AI 決定" if x == "AI" else ("不加倍" if x == 1 else f"{x} 倍"))
    try:
        r = K.advisor_plan(bud, goal, game, mult)
    except ValueError as e:
        r = None
        st.warning(str(e))
    if r:
        b, rows = r
        u = "期" if b["game"] == "賓果" else "注"
        st.warning(f"所有彩券長期都是虧錢:這份方案花 {b['cost']:,} 元,平均拿回約 {b['ev_total']:,.0f} 元(回收率 {b['rtp'] * 100:.1f}%)。")
        st.subheader(f"🤖 建議:{b['name']} ・ {b['n']} {u} × {b['price']:,} 元")
        for i, t in enumerate(K.advisor_tickets(b["game"], b["stars"], b["n"])[:20], 1):
            st.markdown(f"第 {i} 注 " + balls(t["nums"], t.get("second")), unsafe_allow_html=True)
        if b["game"] == "賓果" and b["n"] > K.BINGO_MAX_PERIODS:
            st.caption(f"每張投注單最多連買 12 期,{b['n']} 期需分 {b['slips']} 張。")
        a, c, d, e = st.columns(4)
        a.metric("至少中一次", f"{b['p_any'] * 100:.1f}%"); c.metric("淨賺機率", f"{b['p_gain'] * 100:.2f}%")
        d.metric("回本以上", f"{b['p_even'] * 100:.2f}%"); e.metric("平均虧損", f"{b['loss']:,.0f} 元")
        if len(b["mult_rows"]) > 1:
            st.markdown("**✖️ 加倍比較**")
            st.dataframe(pd.DataFrame([(("★ " if x["mult"] == b["mult"] else "") + f"{x['mult']} 倍", x["n"], f"{x['p_gain'] * 100:.2f}%", f"{x['ev_total']:,.0f}", f"{x['top_prize']:,}") for x in b["mult_rows"]], columns=["倍數", "期數", "淨賺機率", "平均拿回", "單期最高獎"]), hide_index=True)
        st.markdown("**⚖️ 各玩法比較**")
        st.dataframe(pd.DataFrame([(x["name"], x["n"], f"{x['p_any'] * 100:.1f}%", f"{x['p_gain'] * 100:.2f}%", f"{x['rtp'] * 100:.1f}%", K.fmt_prob(x["p_top"])) for x in rows], columns=["玩法", "注/期", "至少中獎", "淨賺", "回收率", "頭獎/全中"]), hide_index=True)
        for t in K.advisor_reasons(b, goal, game, rows):
            st.write("• " + t)
    st.caption("⚠️ 開獎為獨立隨機事件,沒有任何方法能提高中獎機率,請只用輸掉也無妨的錢。")

elif page == PAGES[9]:
    hero("📸 大頭照", "自動轉正、置中裁切不變形,可輸出 4×6 吋整張排版")
    f = st.file_uploader("上傳照片", ["jpg", "jpeg", "png", "webp", "bmp"])
    if f:
        size = K.PHOTO_SIZES[st.selectbox("尺寸", list(K.PHOTO_SIZES), index=1)]
        c1, c2, c3 = st.columns(3)
        cx, cy = c1.slider("左右", 0.0, 1.0, 0.5), c2.slider("上下(小=偏上)", 0.0, 1.0, 0.4)
        sheet = c3.checkbox("排滿 4×6 吋相紙")
        img = K.flatten_rgb(K.ImageOps.exif_transpose(K.Image.open(f)))
        out = K.crop_photo(img, size, cx, cy)
        if sheet:
            out, cnt = K.make_sheet(out)
            st.caption(f"相紙共 {cnt} 張")
        st.image(out)
        buf = io.BytesIO(); out.save(buf, "JPEG", quality=95, dpi=(300, 300))
        st.download_button("💾 下載 JPG", buf.getvalue(), "photo.jpg", "image/jpeg", type="primary")

else:
    hero("🔧 連線診斷", "確認伺服器能否連到各資料來源(部署後若某項失敗,可能是該網站擋海外 IP)")
    if st.button("開始測試", type="primary"):
        tests = {"電影(開眼)": lambda: f"{len(K.MovieClient().list_cinemas('a02', force=True))} 間戲院",
                 "天氣": lambda: K.fetch_weather("Taipei")["desc"], "油價": lambda: K.fetch_oil()["date"],
                 "股票(證交所/Yahoo)": lambda: K.fetch_stock("0050", "1mo")["src"], "匯率": lambda: f"{len(K.fetch_rates()['rates'])} 種",
                 "發票(財政部)": lambda: K.fetch_invoice_periods()[0]["title"], "賓果(pilio)": lambda: f"{len(K.fetch_bingo())} 期"}
        for name, fn in tests.items():
            try:
                st.success(f"✅ {name}:{fn()}")
            except Exception as e:  # noqa: BLE001
                st.error(f"❌ {name}:{type(e).__name__}: {e}")
