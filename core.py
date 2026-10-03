# -*- coding: utf-8 -*-
"""
🧰 全方位生活助手  (電影時刻 + 天氣 / 油價 / 股票 / 匯率 / 發票 / 賓果 / 樂透 / 大頭照)
=====================================================================================
安裝:   pip install customtkinter requests beautifulsoup4 pillow
資料來源: 股價=臺灣證券交易所(即時 + 日成交,Yahoo 僅備援) 發票=財政部 RSS 賓果/樂透=pilio
          電影=開眼電影網 天氣=wttr.in 油價=台灣中油 匯率=exchangerate-api
執行:   python 全方位生活助手.py
測試:   python 全方位生活助手.py --check      (不開視窗,測試各資料來源是否連得到)
        python 全方位生活助手.py --selftest   (不開視窗,測試內建解析/演算法)

快捷鍵: F5 / Ctrl+R = 重新整理目前分頁
"""
from __future__ import annotations

import html as htmllib
import io
import itertools
import json
import math
import queue
import random
import re
import sys
import threading
import time
import traceback
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import customtkinter as ctk
    from PIL import Image, ImageOps

    HAVE_GUI = True
except ImportError:  # 只跑 --check / --selftest 時不強制需要 GUI 套件
    tk = ttk = messagebox = filedialog = ctk = None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        Image = ImageOps = None
    HAVE_GUI = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ════════════════════════════════════════════════════════════════════
#  共用:網路 / 設定
# ════════════════════════════════════════════════════════════════════
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def make_session(retries: int = 3) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=retries, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6"})
    return s


NET = make_session()


def http_get(url: str, *, timeout=(6, 15), encoding: str | None = None,
             session: requests.Session | None = None, **kw) -> requests.Response:
    """GET;憑證驗證失敗時自動退回不驗證(部分台灣網站憑證鏈不完整)。"""
    sess = session or NET
    try:
        r = sess.get(url, timeout=timeout, **kw)
    except requests.exceptions.SSLError:
        r = sess.get(url, timeout=timeout, verify=False, **kw)
    r.raise_for_status()
    if encoding:
        r.encoding = encoding
    elif not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r


CONFIG_PATH = Path.home() / ".tw_life_assistant.json"
LEGACY_MOVIE_CONFIG = Path.home() / ".tw_movie_showtimes.json"


class Config:
    """極簡設定檔(JSON)。讀寫失敗一律忽略,不影響主程式。"""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        try:
            data = json.loads(path.read_text("utf-8"))
            self.data = data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            self.data = {}
        if not self.data and LEGACY_MOVIE_CONFIG.exists():  # 沿用舊版電影時刻設定
            try:
                old = json.loads(LEGACY_MOVIE_CONFIG.read_text("utf-8"))
                self.data = {"movie_region": old.get("region"), "movie_mode": old.get("mode")}
            except Exception:  # noqa: BLE001
                self.data = {}

    def get(self, key, default=None):
        v = self.data.get(key)
        return default if v is None else v

    def set(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        self.save()

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        except Exception:  # noqa: BLE001
            pass


# ════════════════════════════════════════════════════════════════════
#  資料層 ① 電影時刻 (開眼電影網)
# ════════════════════════════════════════════════════════════════════
BASE = "https://www.atmovies.com.tw"

REGIONS = {  # 開眼電影網的地區代碼(台北頁面同時包含新北市)
    "台北 / 新北": "a02", "基隆": "a01", "桃園": "a03", "新竹": "a35", "苗栗": "a37",
    "台中": "a04", "彰化": "a47", "雲林": "a45", "南投": "a49", "嘉義": "a05",
    "台南": "a06", "高雄": "a07", "屏東": "a87", "宜蘭": "a39", "花蓮": "a38",
    "台東": "a89", "澎湖": "a69", "金門": "a68",
}

RATINGS = {  # 網站圖示 cer_X.gif 對應分級
    "G": ("普遍級", "#2f9e63"),
    "P": ("保護級", "#3b82c4"),
    "F2": ("輔12級", "#d19a1c"),
    "F5": ("輔15級", "#e2732b"),
    "R": ("限制級", "#d0403f"),
}

CINEMA_HREF = re.compile(r"/showtime/(t[0-9a-z]+)/(a\d+)/?(?:\?.*)?$", re.I)
FILM_HREF = re.compile(r"/movie/(f[a-z]{3}\d{5,})/?", re.I)
RATING_IMG = re.compile(r"cer_([A-Za-z0-9]+)\.gif")
DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s*[\(（]\s*([一二三四五六日])\s*[\)）]")
TIME_RE = re.compile(r"\d{1,2}:\d{2}")
DUR_RE = re.compile(r"片長[:：]\s*(\d+)\s*分")
UPDATED_RE = re.compile(r"更新時間[:：]\s*(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})")


@dataclass
class Cinema:
    cid: str
    area: str
    name: str
    group: str = ""
    address: str = ""
    phone: str = ""
    site: str = ""
    ticket: str = ""

    @property
    def url(self) -> str:
        return f"{BASE}/showtime/{self.cid}/{self.area}/"


@dataclass
class Session:
    label: str  # 例如「英語版 · 4DX版」,一般場為空字串
    times: list[str]


@dataclass
class Show:
    film_id: str
    title: str
    rating: str = ""
    duration: int = 0
    poster: str = ""
    sessions: list[Session] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{BASE}/movie/{self.film_id}/"


@dataclass
class Day:
    key: str  # 2026/09/30
    short: str  # 9/30 (三)
    shows: list[Show]


@dataclass
class Schedule:
    cinema: Cinema
    days: list[Day]
    updated: str  # 網站標示的資料更新時間
    fetched_at: datetime


@dataclass
class Film:  # 「依電影」模式的彙整資料
    film_id: str
    title: str
    rating: str = ""
    duration: int = 0
    poster: str = ""
    by_cinema: dict = field(default_factory=dict)  # cid -> {day_key: [Session]}

    @property
    def url(self) -> str:
        return f"{BASE}/movie/{self.film_id}/"


def _clean_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "select", "option"]):
        t.decompose()
    return soup


def parse_cinemas(html: str) -> list[Cinema]:
    """解析地區頁 (/showtime/a02/) → 戲院清單"""
    soup = _clean_soup(html)
    out, seen = [], set()
    for a in soup.find_all("a", href=CINEMA_HREF):
        name = a.get_text(strip=True)
        if not name:
            continue
        cid, area = CINEMA_HREF.search(a["href"]).groups()
        if cid in seen:
            continue
        seen.add(cid)

        group = ""
        prev = a.find_previous(string=re.compile("▼"))
        if prev:
            g = prev.strip().replace("▼", "").strip()
            if 0 < len(g) <= 12:
                group = g

        address = phone = site = ticket = ""
        li = a.find_parent("li")
        if li is not None and len(li.find_all("a", href=CINEMA_HREF)) == 1:
            for x in li.find_all("a", href=True):
                lt = x.get_text(strip=True)
                if lt == "網站":
                    site = urljoin(BASE, x["href"])
                elif "訂票" in lt:
                    ticket = urljoin(BASE, x["href"])
            rest = [
                s.strip()
                for s in li.stripped_strings
                if s.strip() not in ("網站", "地圖", "網路訂票", name)
            ]
            if rest:
                address = rest[0]
            if len(rest) > 1:
                phone = rest[1]
        out.append(Cinema(cid, area, name, group, address, phone, site, ticket))
    return out


def parse_schedule(html: str, cinema: Cinema) -> Schedule:
    """解析單一戲院頁 (/showtime/t02a01/a02/) → 各日期、各電影場次"""
    soup = _clean_soup(html)
    page_text = soup.get_text(" ", strip=True)
    um = UPDATED_RE.search(page_text)
    updated = um.group(1) if um else ""

    days: list[dict] = []
    day = None
    cur = None

    def start_day(key: str, short: str):
        nonlocal day, cur
        if day is not None and day["key"] == key:
            return
        day = {"key": key, "short": short, "blocks": []}
        days.append(day)
        cur = None

    for tag in soup.find_all(True):
        name = tag.name

        if name == "img":
            src = tag.get("src", "")
            if cur is not None:
                rm = RATING_IMG.search(src)
                if rm and not cur["rating"] and rm.group(1) in RATINGS:
                    cur["rating"] = rm.group(1)
                if "photo101" in src and not cur["poster"]:
                    cur["poster"] = urljoin(BASE, src)
            continue

        text = tag.get_text(" ", strip=True)
        if not text:
            continue

        # ── 日期標題 ─────────────────────────────
        if len(text) <= 30 and name not in ("a", "html", "body"):
            dm = DATE_RE.match(text)
            if dm:
                y, mo, d, wd = dm.groups()
                start_day(f"{y}/{int(mo):02d}/{int(d):02d}", f"{int(mo)}/{int(d)} ({wd})")
                continue

        # ── 電影標題連結 ─────────────────────────
        if name == "a":
            fm = FILM_HREF.search(tag.get("href", ""))
            if fm:
                if text.startswith(("/", "http", "movie/")) or "其他戲院" in text:
                    continue
                fid = fm.group(1)
                if cur is not None and cur["film_id"] == fid and not cur["times"]:
                    continue
                if day is None:
                    today = datetime.now()
                    wd = "一二三四五六日"[today.weekday()]
                    start_day(today.strftime("%Y/%m/%d"), f"{today.month}/{today.day} ({wd})")
                cur = {
                    "film_id": fid, "title": text, "rating": "", "duration": 0,
                    "poster": "", "labels": [], "times": [],
                }
                day["blocks"].append(cur)
                continue

        if cur is None:
            continue

        # ── 場次時間 ─────────────────────────────
        norm = text.replace("：", ":")
        if TIME_RE.fullmatch(norm) and name in ("li", "a", "span", "td", "div", "p", "b", "strong"):
            if any(k.get_text(" ", strip=True) == text for k in tag.find_all(True, recursive=False)):
                continue  # 交給最內層元素,避免重複計算
            h, m = norm.split(":")
            cur["times"].append(f"{int(h):02d}:{m}")
            continue

        # ── 片長 / 版本標籤 ──────────────────────
        if name == "li" and not tag.find(["li", "ul"]):
            if tag.find("a", href=FILM_HREF):
                continue
            dm = DUR_RE.search(text)
            if dm:
                cur["duration"] = int(dm.group(1))
                continue
            if "其他戲院" in text:
                continue
            if not cur["times"] and len(text) <= 30:
                cur["labels"].append(text)

    out_days = []
    for d in days:
        shows: dict[str, Show] = {}
        for b in d["blocks"]:
            if not b["times"]:
                continue
            s = shows.get(b["film_id"])
            if s is None:
                s = shows[b["film_id"]] = Show(b["film_id"], b["title"])
            s.rating = s.rating or b["rating"]
            s.duration = s.duration or b["duration"]
            s.poster = s.poster or b["poster"]
            s.sessions.append(Session(" · ".join(b["labels"]), b["times"]))
        if shows:
            out_days.append(Day(d["key"], d["short"], list(shows.values())))
    return Schedule(cinema, out_days, updated, datetime.now())


def build_index(schedules: dict[str, Schedule]) -> dict[str, Film]:
    idx: dict[str, Film] = {}
    for cid, sch in schedules.items():
        for day in sch.days:
            for sh in day.shows:
                f = idx.get(sh.film_id)
                if f is None:
                    f = idx[sh.film_id] = Film(sh.film_id, sh.title)
                f.rating = f.rating or sh.rating
                f.duration = f.duration or sh.duration
                f.poster = f.poster or sh.poster
                f.by_cinema.setdefault(cid, {})[day.key] = sh.sessions
    return idx


def is_past(day_key: str, hhmm: str, now: datetime) -> bool:
    """場次是否已開演。凌晨 0~5 點的場次算在當天營業日的深夜(+24h)。"""
    try:
        y, mo, d = (int(x) for x in day_key.split("/"))
        day = datetime(y, mo, d).date()
    except ValueError:
        return False
    if day != now.date():
        return day < now.date()
    h, m = (int(x) for x in hhmm.split(":"))
    mins = h * 60 + m + (1440 if h < 6 else 0)
    return mins < now.hour * 60 + now.minute


class MovieClient:
    """帶重試與短時間快取的 HTTP 客戶端。force=True 會略過快取,直接抓最新。"""

    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self.session = make_session()
        self.session.headers.update({"Referer": BASE + "/"})
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get_html(self, url: str, force: bool = False) -> str:
        if not force:
            with self._lock:
                hit = self._cache.get(url)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"} if force else {}
        html = http_get(url, timeout=(6, 20), session=self.session, headers=headers).text
        with self._lock:
            self._cache[url] = (time.time(), html)
        return html

    def list_cinemas(self, region_code: str, force: bool = False) -> list[Cinema]:
        return parse_cinemas(self.get_html(f"{BASE}/showtime/{region_code}/", force))

    def get_schedule(self, cinema: Cinema, force: bool = False) -> Schedule:
        return parse_schedule(self.get_html(cinema.url, force), cinema)


# ════════════════════════════════════════════════════════════════════
#  資料層 ② 賓果 / 樂透
# ════════════════════════════════════════════════════════════════════
BINGO_URL = "https://www.pilio.idv.tw/bingo/list.asp"
BINGO_ID_RE = re.compile(r"(?<!\d)(1[1-9]\d{7})(?!\d)")  # 期數:民國年3碼 + 流水號6碼


def parse_bingo(html: str) -> list[dict]:
    """解析賓果歷史頁 → [{'期數': int, '號碼': [20個號碼]}],新到舊。"""
    soup = BeautifulSoup(html, "html.parser")
    data, seen = [], set()
    for row in soup.find_all("tr"):
        text = row.get_text(" ", strip=True)  # 用空白分隔,避免相鄰欄位的數字黏在一起
        m = BINGO_ID_RE.search(text)
        if not m:
            continue
        draw_id = int(m.group(1))
        if draw_id in seen:
            continue
        nums: list[int] = []
        for t in re.findall(r"(?<![\d/:.])\d{1,2}(?![\d/:.])", text[m.end():]):
            n = int(t)
            if 1 <= n <= 80 and n not in nums:
                nums.append(n)
        if len(nums) < 20:  # 退而求其次:沿用舊版寬鬆解析
            nums = []
            for t in re.findall(r"\d+", text):
                n = int(t)
                if 1 <= n <= 80 and n != draw_id and n not in nums:
                    nums.append(n)
        if len(nums) >= 20:
            data.append({"期數": draw_id, "號碼": nums[:20]})
            seen.add(draw_id)
    data.sort(key=lambda d: d["期數"], reverse=True)
    return data


def fetch_bingo() -> list[dict]:
    return parse_bingo(http_get(BINGO_URL, encoding="big5", timeout=(6, 12)).text)


def bingo_freq(draws: list[dict], periods: int) -> Counter:
    c: Counter = Counter()
    for d in draws[:periods]:
        c.update(d["號碼"])
    return c


def bingo_omission(draws: list[dict]) -> dict[int, int]:
    """遺漏值:每個號碼距離上次開出隔了幾期(0 = 最近一期就開出)。"""
    om = {n: len(draws) for n in range(1, 81)}
    for i, d in enumerate(draws):
        for n in d["號碼"]:
            if om[n] == len(draws):
                om[n] = i
    return om


def bingo_pick(draws: list[dict], mode: str, stars: int, periods: int = 50) -> list[int]:
    """依策略挑號。"""
    if not draws:
        return []
    freq = bingo_freq(draws, periods)
    hot = [n for n, _ in sorted(((n, freq.get(n, 0)) for n in range(1, 81)), key=lambda x: (-x[1], x[0]))]
    cold = [n for n, _ in sorted(((n, freq.get(n, 0)) for n in range(1, 81)), key=lambda x: (x[1], x[0]))]
    if mode == "hot":
        return sorted(hot[:stars])
    if mode == "cold":
        return sorted(cold[:stars])
    if mode == "mix":
        half = stars // 2
        pick = hot[:half]
        for n in cold:
            if len(pick) >= stars:
                break
            if n not in pick:
                pick.append(n)
        return sorted(pick)
    if mode == "omit":
        om = bingo_omission(draws)
        return sorted(sorted(range(1, 81), key=lambda n: (-om[n], n))[:stars])
    if mode == "random":
        return sorted(random.sample(range(1, 81), stars))
    return []


def bingo_backtest(draws: list[dict], picks: list[int], periods: int) -> dict:
    rows, total, wins = [], 0, 0
    pset = set(picks)
    need = len(picks) / 2 + 0.5  # 命中過半視為「贏」
    for d in draws[:periods]:
        hit = sorted(pset & set(d["號碼"]))
        total += len(hit)
        win = len(hit) >= need
        wins += win
        rows.append({"期數": d["期數"], "命中": hit, "贏": win, "號碼": d["號碼"]})
    n = len(rows)
    return {
        "rows": rows, "n": n,
        "avg": total / n if n else 0.0,
        "win_rate": wins / n * 100 if n else 0.0,
        "expect": len(picks) * 20 / 80,  # 完全亂選的期望命中數
    }


LOTTO_RULES = {
    "大樂透": dict(max_n=49, pick=6, sum=(115, 185), min_ac=7, odds=(2, 3, 4), url="https://www.pilio.idv.tw/ltobig/list.asp"),
    "威力彩": dict(max_n=38, pick=6, sum=(85, 145), min_ac=7, odds=(2, 3, 4), url="https://www.pilio.idv.tw/lto/list.asp"),
    "今彩539": dict(max_n=39, pick=5, sum=(75, 125), min_ac=4, odds=(2, 3), url="https://www.pilio.idv.tw/lto539/list.asp"),
}


def calc_ac(numbers) -> int:
    """AC 值(算術複雜度):不同差值個數 − (號碼數 − 1)。"""
    diffs = {abs(a - b) for a, b in itertools.combinations(numbers, 2)}
    return len(diffs) - (len(numbers) - 1)


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    return all(n % i for i in range(2, int(n ** 0.5) + 1))


def has_arith_progression(combo, length: int = 4) -> bool:
    """號碼中是否含有長度 >= length 的等差數列(例如 5-10-15-20,在投注單上會連成直線/斜線)。"""
    s = set(combo)
    for a in combo:
        for b in combo:
            if b > a:
                d = b - a
                if all(a + d * i in s for i in range(length)):
                    return True
    return False


def crowd_penalty(combo, max_n: int) -> int:
    """估計一組號碼有多『大眾化』(越多人會選同一組 → 中獎時分到的獎金越少)。0 = 不明顯大眾化。"""
    pen = 0
    if all(n <= 31 for n in combo):  # 全是生日/日期號碼,是最常見的選法
        pen += 1
    if sum(1 for n in combo if n <= 12) >= 3:  # 月份號碼太多
        pen += 1
    run = best = 1
    for a, b in zip(combo, combo[1:]):
        run = run + 1 if b - a == 1 else 1
        best = max(best, run)
    if best >= 3:  # 連續三碼以上
        pen += 1
    if has_arith_progression(combo, 4):  # 等差數列(投注單上的直線、斜線)
        pen += 1
    if max(Counter(n % 10 for n in combo).values()) >= 3:  # 三個以上同尾數
        pen += 1
    return pen


LOTTO_MODES = {"anti": "避開大眾選號", "random": "純隨機", "structure": "傳統結構篩選"}


def generate_tickets(kind: str, count: int, progress=None, rng=random, max_attempts: int = 150000,
                     mode: str = "anti") -> list[dict]:
    """產生號碼。
    anti      避開大眾選號:不會提高中獎機率,只降低『和別人同一組、必須分獎』的機會。
    random    純隨機。
    structure 傳統『和值/AC值/奇偶/連號/質數/分區』篩選(民間說法,沒有統計上的優勢)。
    """
    rule = LOTTO_RULES[kind]
    max_n, pick = rule["max_n"], rule["pick"]
    primes = {n for n in range(1, max_n + 1) if is_prime(n)}
    tickets: list[dict] = []
    seen: set[tuple] = set()
    attempts = 0
    while len(tickets) < count and attempts < max_attempts:
        attempts += 1
        if progress and attempts % 2000 == 0:
            progress(min(len(tickets) / count, 0.99))
        combo = sorted(rng.sample(range(1, max_n + 1), pick))
        s = sum(combo)
        ac = calc_ac(combo)
        if mode == "anti":
            if crowd_penalty(combo, max_n) > 0:
                continue
        elif mode == "structure":
            if not (rule["sum"][0] <= s <= rule["sum"][1]) or ac < rule["min_ac"]:
                continue
            if sum(n % 2 for n in combo) not in rule["odds"]:
                continue
            if sum(1 for a, b in zip(combo, combo[1:]) if b - a == 1) > 1:
                continue
            if not (1 <= sum(1 for n in combo if n in primes) <= 3):
                continue
            if len({n // 10 for n in combo}) < 3:
                continue
        key = tuple(combo)
        if key in seen:
            continue
        seen.add(key)
        tickets.append({"nums": combo, "ac": ac, "sum": s})
    return tickets


def _parse_lotto_page(text: str, kind: str) -> list[dict]:
    txt = re.sub(r"<[^>]+>", " ", text)
    min_n = 5 if kind == "今彩539" else 7
    matches = []
    for m in re.finditer(r"(\d{2}/\d{2})\s+(\d{2})", txt):
        matches.append({"d": f"20{m.group(2)}/{m.group(1)}", "s": m.end()})
    for m in re.finditer(r"(\d{4}/\d{2}/\d{2})", txt):
        matches.append({"d": m.group(1), "s": m.end()})
    matches.sort(key=lambda x: x["s"])
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1]["s"] if i < len(matches) - 1 else len(txt)
        nums = re.findall(r"\b\d{2}\b", txt[m["s"]:end])
        if len(nums) >= min_n:
            if kind == "今彩539":
                out.append({"日期": m["d"], "獎號": nums[:5], "特別號": None})
            else:
                out.append({"日期": m["d"], "獎號": nums[:6], "特別號": nums[6]})
    return out


def fetch_lotto_history(kind: str, pages: int = 3) -> list[dict]:
    """抓近幾頁開獎紀錄(平行下載)。任何頁面失敗都略過。"""
    base_url = LOTTO_RULES[kind]["url"]

    def one(p):
        try:
            r = http_get(f"{base_url}?indexpage={p}", encoding="big5", timeout=(6, 10))
            return p, _parse_lotto_page(r.text, kind)
        except Exception:  # noqa: BLE001
            return p, []

    with ThreadPoolExecutor(pages) as ex:
        results = dict(ex.map(one, range(1, pages + 1)))
    out: list[dict] = []
    for p in sorted(results):
        out.extend(results[p])
    return out


def hot_second_zone(history: list[dict], recent: int = 20) -> int | None:
    """威力彩第二區(1~8)近期最常開出的號碼。"""
    vals = [int(h["特別號"]) for h in history[:recent] if h.get("特別號") and str(h["特別號"]).isdigit()]
    vals = [v for v in vals if 1 <= v <= 8]
    return Counter(vals).most_common(1)[0][0] if vals else None


# ════════════════════════════════════════════════════════════════════
#  資料層 ③ 天氣 / 油價 / 股票 / 匯率 / 發票
# ════════════════════════════════════════════════════════════════════
def _to_int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _wx_text(node: dict) -> str:
    try:
        return node["lang_zh-tw"][0]["value"]
    except (KeyError, IndexError, TypeError):
        pass
    try:
        return node["weatherDesc"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return ""


def weather_icon(desc: str) -> str:
    d = desc.lower()
    if "雷" in d or "thunder" in d:
        return "⛈️"
    if "雪" in d or "snow" in d or "sleet" in d:
        return "❄️"
    if "雨" in d or "rain" in d or "drizzle" in d or "shower" in d:
        return "🌧️"
    if "霧" in d or "fog" in d or "mist" in d:
        return "🌫️"
    if "晴" in d or "sunny" in d or "clear" in d:
        return "☀️"
    if "多雲" in d or "partly" in d:
        return "⛅"
    if "雲" in d or "cloud" in d or "陰" in d or "overcast" in d:
        return "☁️"
    return "⛅"


def clothing_advice(feel: int, rain: int, uv: int = 0) -> str:
    if feel >= 30:
        s = "🔥 非常炎熱!穿短袖短褲,多喝水、注意防曬與中暑。"
    elif feel >= 25:
        s = "😎 天氣偏熱,建議透氣的短袖或薄衫。"
    elif feel >= 20:
        s = "😊 舒適宜人,短袖搭配薄外套即可。"
    elif feel >= 15:
        s = "🍃 有點涼意,建議長袖、帽T或夾克。"
    elif feel >= 10:
        s = "🧥 天氣寒冷,請穿厚外套或毛衣,注意保暖。"
    else:
        s = "🥶 極冷!羽絨衣、圍巾、手套全副武裝。"
    if rain >= 40:
        s += "\n☔ 降雨機率偏高,出門記得帶傘。"
    if uv >= 6:
        s += "\n🧴 紫外線強,外出請擦防曬、戴帽子。"
    return s


def parse_weather(j: dict) -> dict:
    cur = j["current_condition"][0]
    days = []
    for d in (j.get("weather") or [])[:3]:
        hours = d.get("hourly") or []
        rain = max([_to_int(h.get("chanceofrain")) for h in hours] or [0])
        mid = hours[4] if len(hours) > 4 else (hours[len(hours) // 2] if hours else {})
        label = d.get("date", "")
        try:
            dt = datetime.strptime(label, "%Y-%m-%d")
            label = f"{dt.month}/{dt.day} ({'一二三四五六日'[dt.weekday()]})"
        except ValueError:
            pass
        desc = _wx_text(mid) if mid else ""
        days.append({"label": label, "hi": d.get("maxtempC", "-"), "lo": d.get("mintempC", "-"),
                     "rain": rain, "desc": desc, "icon": weather_icon(desc)})
    area = ""
    try:
        area = j["nearest_area"][0]["areaName"][0]["value"]
    except (KeyError, IndexError, TypeError):
        pass
    desc = _wx_text(cur)
    desc_en = ""
    try:
        desc_en = cur["weatherDesc"][0]["value"]
    except (KeyError, IndexError, TypeError):
        pass
    return {
        "area": area, "temp": cur.get("temp_C", "-"), "feel": cur.get("FeelsLikeC", "-"),
        "humid": cur.get("humidity", "-"), "wind": cur.get("windspeedKmph", "-"),
        "uv": cur.get("uvIndex", "0"), "vis": cur.get("visibility", "-"),
        "desc": desc or desc_en, "icon": weather_icon(f"{desc} {desc_en}"),
        "rain": days[0]["rain"] if days else 0, "days": days,
    }


def fetch_weather(city: str) -> dict:
    r = http_get(f"https://wttr.in/{quote(city)}", params={"format": "j1", "lang": "zh-tw"}, timeout=(6, 15))
    return parse_weather(r.json())


OIL_HISTORY_URL = "https://www.cpc.com.tw/historyprice.aspx?n=2890"
OIL_API_URL = "https://vipmbr.cpc.com.tw/CPCSTN/ListPriceWebService.asmx/getCPCMainProdListPrice_Chinese"
OIL_NAMES = ["92 無鉛汽油", "95 無鉛汽油", "98 無鉛汽油", "超級柴油"]


def _price(s: str) -> float | None:
    try:
        v = float(str(s).replace(",", "").strip())
    except ValueError:
        return None
    return v if 5 <= v <= 200 else None


def parse_cpc_history(html: str) -> list[tuple[str, list[float]]]:
    """歷史牌價表 → [(日期, [92, 95, 98, 柴油])],新到舊。"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        tds = [t.get_text(strip=True) for t in tr.find_all("td")]
        if len(tds) >= 5 and "/" in tds[0]:
            prices = [_price(x) for x in tds[1:5]]
            if all(p is not None for p in prices):
                out.append((tds[0], prices))
    return out


def parse_cpc_api(text: str) -> tuple[str, list[float]] | None:
    """中油即時牌價 API(XML 包 JSON) → (更新時間, [92, 95, 98, 柴油])"""
    m = re.search(r"\[.*\]", htmllib.unescape(text), re.S)
    if not m:
        return None
    try:
        items = json.loads(m.group(0))
    except ValueError:
        return None
    found: dict[int, float] = {}
    stamp = ""
    for it in items:
        name = str(it.get("產品名稱", ""))
        price = _price(it.get("參考牌價", ""))
        stamp = stamp or str(it.get("更新時間", it.get("生效日期", "")))
        if price is None:
            continue
        for idx, key in enumerate(("92", "95", "98", "柴油")):
            if key in name and idx not in found:
                found[idx] = price
    if len(found) == 4:
        return stamp, [found[i] for i in range(4)]
    return None


def fetch_oil() -> dict:
    """優先讀歷史牌價表(可算漲跌);失敗再退回即時 API。"""
    err: Exception | None = None
    try:
        html = http_get(OIL_HISTORY_URL, encoding="utf-8", timeout=(6, 12)).text
        rows = parse_cpc_history(html)
        if rows:
            prev = rows[1][1] if len(rows) > 1 else None
            return {"date": rows[0][0], "prices": rows[0][1], "prev": prev, "src": "中油歷史牌價"}
    except Exception as e:  # noqa: BLE001
        err = e
    try:
        text = http_get(OIL_API_URL, timeout=(6, 12)).text
        res = parse_cpc_api(text)
        if res:
            return {"date": res[0], "prices": res[1], "prev": None, "src": "中油即時牌價"}
    except Exception as e:  # noqa: BLE001
        err = err or e
    raise RuntimeError(f"讀不到中油牌價({err or '格式不符'})")


STOCK_RANGES = {"1個月": "1mo", "3個月": "3mo", "6個月": "6mo", "1年": "1y"}
TW_TZ = timezone(timedelta(hours=8))
MIS_HOME = "https://mis.twse.com.tw/stock/index.jsp"
MIS_API = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_DAY_API = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
_mis_session = make_session(retries=1)


def _num(s) -> float | None:
    try:
        v = float(str(s).replace(",", "").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def tw_now() -> datetime:
    return datetime.now(TW_TZ)


def market_open(now: datetime | None = None) -> bool:
    """台股盤中(週一~五 09:00~13:30;國定假日無法判斷,另以資料日期交叉確認)。"""
    now = now or tw_now()
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (13, 30)


def _d8(s) -> str:
    s = str(s or "")
    return f"{s[:4]}/{s[4:6]}/{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


def parse_twse_day(j: dict) -> list[dict]:
    """證交所『個股日成交資訊』→ [{date, open, high, low, close, vol(股)}],舊到新。"""
    if not isinstance(j, dict) or j.get("stat") != "OK":
        return []
    out = []
    for row in j.get("data") or []:
        try:
            y, mo, d = row[0].split("/")
            close = _num(row[6])
            if close is None:  # 當日無成交顯示 "--"
                continue
            out.append({"date": f"{int(y) + 1911}/{int(mo):02d}/{int(d):02d}", "open": _num(row[3]),
                        "high": _num(row[4]), "low": _num(row[5]), "close": close, "vol": _num(row[1])})
        except (ValueError, IndexError, AttributeError):
            continue
    out.sort(key=lambda r: r["date"])
    return out


def parse_mis(j: dict, code: str) -> dict | None:
    """證交所『基本市況報導』即時資料。z=最新成交價 y=昨收 v=累計成交量(張)。"""
    for it in (j or {}).get("msgArray") or []:
        if it.get("c") != code or not it.get("n"):
            continue
        return {"name": it["n"], "ex": it.get("ex"), "price": _num(it.get("z")), "prev": _num(it.get("y")),
                "open": _num(it.get("o")), "high": _num(it.get("h")), "low": _num(it.get("l")),
                "volume": _num(it.get("v")), "date": it.get("d", ""), "time": it.get("t", "")}
    return None


def fetch_mis(code: str) -> dict | None:
    for attempt in range(2):
        if attempt or not _mis_session.cookies:  # 需先造訪首頁取得 session cookie
            http_get(MIS_HOME, session=_mis_session, timeout=(6, 10))
        r = http_get(MIS_API, session=_mis_session, timeout=(6, 10), headers={"Referer": MIS_HOME},
                     params={"ex_ch": f"tse_{code}.tw|otc_{code}.tw", "json": "1", "delay": "0",
                             "_": int(time.time() * 1000)})
        data = parse_mis(r.json(), code)
        if data:
            return data
    return None


_twse_cache: dict[str, tuple[float, list[dict]]] = {}


def fetch_twse_recent(code: str, months: int = 2) -> list[dict]:
    """近兩個月日成交資料。盤中時(今天的資料尚未產生)快取 10 分鐘,避免自動更新時頻繁請求被證交所限流。"""
    hit = _twse_cache.get(code)
    if hit and market_open() and time.time() - hit[0] < 600:
        return hit[1]
    now, rows = tw_now(), []
    y, m = now.year, now.month
    for _ in range(months):
        r = http_get(TWSE_DAY_API, timeout=(6, 10),
                     params={"response": "json", "date": f"{y}{m:02d}01", "stockNo": code})
        rows += parse_twse_day(r.json())
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["date"]):
        if r["date"] not in seen:
            seen.add(r["date"])
            out.append(r)
    _twse_cache[code] = (time.time(), out)
    return out


def parse_yahoo_chart(j: dict) -> dict | None:
    chart = j.get("chart") or {}
    res = (chart.get("result") or [None])[0]
    if not res:
        return None
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    off = timedelta(seconds=meta.get("gmtoffset", 28800))
    labels, values = [], []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        labels.append((datetime.fromtimestamp(t, timezone.utc) + off).strftime("%Y/%m/%d"))
        values.append(float(c))
    price = meta.get("regularMarketPrice")
    if price is None and values:
        price = values[-1]
    if price is None:
        return None
    prev = values[-2] if len(values) >= 2 else meta.get("previousClose") or meta.get("chartPreviousClose")
    if not prev:
        prev = price
    return {
        "name": meta.get("longName") or meta.get("shortName") or "", "symbol": meta.get("symbol", ""),
        "price": float(price), "prev": float(prev),
        "high": meta.get("regularMarketDayHigh"), "low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
        "hi52": meta.get("fiftyTwoWeekHigh"), "lo52": meta.get("fiftyTwoWeekLow"),
        "labels": labels, "values": values,
    }


def fetch_yahoo(code: str, rng: str) -> dict | None:
    last: Exception | None = None
    for suffix in (".TW", ".TWO"):  # 上市 / 上櫃
        try:
            r = NET.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}",
                        params={"range": rng, "interval": "1d"}, timeout=(6, 12))
            if r.status_code == 404:
                continue
            r.raise_for_status()
            d = parse_yahoo_chart(r.json())
            if d:
                return d
        except Exception as e:  # noqa: BLE001
            last = e
    if last:
        raise last
    return None


def build_stock(code: str, mis: dict | None, official: list[dict], yahoo: dict | None,
                now: datetime | None = None) -> dict:
    """合併多個來源。優先序:證交所即時 → 證交所日成交(收盤後以此為準) → Yahoo(僅備援)。"""
    now = now or tw_now()
    today = now.strftime("%Y/%m/%d")
    o_last = official[-1] if official else None
    o_prev = official[-2] if len(official) >= 2 else None
    m_date = _d8(mis.get("date")) if mis else ""
    price = prev = hi = lo = vol = None
    date_s = clock = src = ""

    if mis and mis.get("price") is not None:
        price, prev = mis["price"], mis.get("prev")
        date_s, clock = m_date, mis.get("time") or ""
        hi, lo, vol = mis.get("high"), mis.get("low"), mis.get("volume")
        live = market_open(now) and m_date == today
        src = "證交所即時成交" if live else "證交所收盤價"
        if not live and o_last and o_last["date"] == m_date:  # 收盤後:以日成交資料的收盤價為準
            price = o_last["close"]
            prev = o_prev["close"] if o_prev else prev
            hi, lo = o_last["high"] or hi, o_last["low"] or lo
            vol = o_last["vol"] / 1000 if o_last.get("vol") else vol
    elif o_last:
        price, prev = o_last["close"], (o_prev["close"] if o_prev else None)
        date_s, hi, lo = o_last["date"], o_last["high"], o_last["low"]
        vol = o_last["vol"] / 1000 if o_last.get("vol") else None
        src = "證交所收盤價"
    elif yahoo:
        price, prev = yahoo["price"], yahoo["prev"]
        date_s = yahoo["labels"][-1] if yahoo["labels"] else ""
        hi, lo = yahoo["high"], yahoo["low"]
        vol = yahoo["volume"] / 1000 if yahoo.get("volume") else None
        src = "Yahoo(可能延遲,僅供參考)"
    else:
        raise RuntimeError(f"查無代號 {code}")
    if prev is None:
        prev = (o_prev["close"] if o_prev else None) or (yahoo["prev"] if yahoo else None) or price

    labels = list(yahoo["labels"]) if yahoo else []
    values = list(yahoo["values"]) if yahoo else []
    if not values and official:
        labels, values = [r["date"] for r in official], [r["close"] for r in official]
    pos = {d: i for i, d in enumerate(labels)}
    for r in official:  # 用官方收盤價校正 Yahoo 歷史資料
        if r["date"] in pos:
            values[pos[r["date"]]] = r["close"]
    if date_s and values:
        if labels[-1] == date_s:
            values[-1] = price
        elif date_s > labels[-1]:
            labels.append(date_s)
            values.append(price)
    return {
        "code": code, "symbol": code, "name": (mis or {}).get("name") or (yahoo or {}).get("name") or "",
        "price": price, "prev": prev, "high": hi, "low": lo, "volume": vol,
        "hi52": (yahoo or {}).get("hi52"), "lo52": (yahoo or {}).get("lo52"),
        "labels": labels, "values": values, "src": src, "asof": f"{date_s} {clock}".strip(),
    }


def fetch_stock(code: str, rng: str = "3mo") -> dict:
    code = code.strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{4,8}", code):
        raise ValueError("股票代號格式不正確")
    errs: list[Exception] = []

    def safe(fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(e)
            return None

    with ThreadPoolExecutor(3) as ex:
        f_mis = ex.submit(safe, lambda: fetch_mis(code))
        f_off = ex.submit(safe, lambda: fetch_twse_recent(code))
        f_yah = ex.submit(safe, lambda: fetch_yahoo(code, rng))
        mis, official, yahoo = f_mis.result(), f_off.result() or [], f_yah.result()
    if not (mis or official or yahoo):
        raise RuntimeError(f"查無代號 {code}" + (f"({errs[0]})" if errs else ""))
    return build_stock(code, mis, official, yahoo)


FX_CURRENCIES = [
    ("TWD", "🇹🇼", "新台幣"), ("USD", "🇺🇸", "美元"), ("JPY", "🇯🇵", "日圓"), ("EUR", "🇪🇺", "歐元"),
    ("CNY", "🇨🇳", "人民幣"), ("HKD", "🇭🇰", "港幣"), ("KRW", "🇰🇷", "韓元"), ("GBP", "🇬🇧", "英鎊"),
    ("AUD", "🇦🇺", "澳幣"), ("SGD", "🇸🇬", "新加坡幣"), ("THB", "🇹🇭", "泰銖"), ("VND", "🇻🇳", "越南盾"),
]


def fetch_rates() -> dict:
    r = http_get("https://api.exchangerate-api.com/v4/latest/TWD", timeout=(6, 10))
    j = r.json()
    rates = j.get("rates") or {}
    if not rates:
        raise ValueError("匯率資料為空")
    return {"rates": rates, "date": j.get("date", ""), "got": time.time()}


def fx_convert(amount: float, src: str, dst: str, rates: dict) -> float:
    """rates 以 TWD 為基準:1 TWD = rates[X] X。"""
    if src == dst:
        return amount
    return amount / rates[src] * rates[dst]


def parse_amount(s: str) -> float | None:
    s = s.replace(",", "").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) and v >= 0 else None


INVOICE_TIERS = [(8, "頭獎", 200_000), (7, "二獎", 40_000), (6, "三獎", 10_000),
                 (5, "四獎", 4_000), (4, "五獎", 1_000), (3, "六獎", 200)]


def split_numbers(s: str, width: int) -> list[str]:
    """把使用者輸入的一串號碼(空白/逗號/換行分隔)取出符合位數的數字。"""
    return [t for t in re.split(r"[^0-9]+", s) if len(t) == width]


def check_invoice(num: str, special: list[str], grand: list[str], firsts: list[str], extra6: list[str]) -> dict:
    """回傳 {'ok': bool, 'prize': str, 'amount': int, 'note': str}"""
    d = re.sub(r"\D", "", num)
    if len(d) == 3:
        hit = [f for f in firsts if f.endswith(d)]
        if hit or d in extra6:
            return {"ok": True, "prize": "末三碼相符", "amount": 200,
                    "note": "至少可中六獎 200 元,請輸入完整 8 碼確認是否有更高獎項"}
        return {"ok": False, "prize": "未中獎", "amount": 0, "note": "末三碼未中六獎(輸入完整 8 碼才能判斷其他獎項)"}
    if len(d) != 8:
        return {"ok": False, "prize": "格式錯誤", "amount": 0, "note": "請輸入 8 碼發票號碼或末 3 碼"}
    if d in special:
        return {"ok": True, "prize": "特別獎", "amount": 10_000_000, "note": "恭喜!請儘速兌獎"}
    if d in grand:
        return {"ok": True, "prize": "特獎", "amount": 2_000_000, "note": "恭喜!請儘速兌獎"}
    best = None
    for f in firsts:
        for k, name, amt in INVOICE_TIERS:
            if d[-k:] == f[-k:]:
                if best is None or amt > best[1]:
                    best = (name, amt)
                break
    if d[-3:] in extra6 and (best is None or best[1] < 200):
        best = ("增開六獎", 200)
    if best:
        return {"ok": True, "prize": best[0], "amount": best[1], "note": "請核對發票並至郵局或銀行兌獎"}
    return {"ok": False, "prize": "未中獎", "amount": 0, "note": ""}


INVOICE_RSS = "https://invoice.etax.nat.gov.tw/invoice.xml"


def claim_window(roc_year: int, end_month: int) -> tuple[date, date]:
    """領獎期間:開獎次月 6 日起,連續 3 個月,至第 3 個月 5 日止(例:01~02月 → 4/6 ~ 7/5)。"""
    y, m = roc_year + 1911, end_month + 2
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    start = date(y, m, 6)
    y2, m2 = y, m + 3
    y2, m2 = y2 + (m2 - 1) // 12, (m2 - 1) % 12 + 1
    return start, date(y2, m2, 5)


def parse_invoice_rss(content) -> list[dict]:
    """財政部 RSS → 最近數期中獎號碼(新到舊)。"""
    root = ET.fromstring(content)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        tm = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*[~～\-－]\s*(\d{1,2})\s*月", title)
        text = re.sub(r"<[^>]+>", " ", htmllib.unescape(item.findtext("description") or ""))
        sp = re.search(r"特別獎[:：]\s*(\d{8})", text)
        gr = re.search(r"(?<!別)特獎[:：]\s*(\d{8})", text)
        fi = re.search(r"頭獎[:：]\s*([\d、，,\s]+)", text)
        ex = re.search(r"增開六獎[:：]\s*([\d、，,\s]+)", text)
        if not (tm and sp and gr and fi):
            continue
        roc, m_end = int(tm.group(1)), int(tm.group(3))
        start, end = claim_window(roc, m_end)
        out.append({
            "title": f"{roc}年 {int(tm.group(2)):02d}~{m_end:02d}月", "roc": roc, "m_end": m_end,
            "special": [sp.group(1)], "grand": [gr.group(1)],
            "first": split_numbers(fi.group(1), 8), "extra": split_numbers(ex.group(1), 3) if ex else [],
            "claim_start": start.isoformat(), "claim_end": end.isoformat(),
        })
    return out


def fetch_invoice_periods() -> list[dict]:
    r = http_get(INVOICE_RSS, timeout=(6, 12))
    periods = parse_invoice_rss(r.content)
    if not periods:
        raise ValueError("讀取到財政部網站,但解析不到中獎號碼")
    return periods


# ════════════════════════════════════════════════════════════════════
#  資料層 ⑤ 機率與期望值(賓果 / 樂透)
# ════════════════════════════════════════════════════════════════════
# 台灣彩券官方「基本玩法」固定獎金(每注 25 元)。{星數: {對中個數: 獎金}}
BINGO_PRICE = 25
BINGO_PAYOUT = {
    1: {1: 50},
    2: {2: 75, 1: 25},
    3: {3: 500, 2: 50},
    4: {4: 1000, 3: 100, 2: 25},
    5: {5: 7500, 4: 500, 3: 50},
    6: {6: 25000, 5: 1000, 4: 200, 3: 25},
    7: {7: 80000, 6: 3000, 5: 300, 4: 50, 3: 25},
    8: {8: 500000, 7: 20000, 6: 1000, 5: 200, 4: 25, 0: 25},
    9: {9: 1000000, 8: 100000, 7: 3000, 6: 500, 5: 100, 4: 25, 0: 25},
    10: {10: 5000000, 9: 250000, 8: 25000, 7: 2500, 6: 250, 5: 25, 0: 25},
}
# 台灣彩券公布的「總中獎率約 1/x」,用來交叉驗證上面的獎金表與機率計算
BINGO_PUBLISHED_ODDS = {1: 4, 2: 2.27, 3: 6.55, 4: 3.86, 5: 10.34, 6: 6.19, 7: 4.23, 8: 5.25, 9: 4.61, 10: 9.05}


def bingo_odds(stars: int) -> dict:
    """選 stars 個號碼,80 取 20 開獎時,恰好對中 k 個的精確機率(超幾何分佈)與期望值。"""
    pay = BINGO_PAYOUT[stars]
    total = math.comb(80, stars)
    rows, ev, win = [], 0.0, 0.0
    for k in range(stars + 1):
        p = math.comb(20, k) * math.comb(60, stars - k) / total
        prize = pay.get(k, 0)
        ev += p * prize
        win += p if prize else 0.0
        rows.append({"hits": k, "p": p, "prize": prize, "ev": p * prize})
    return {"stars": stars, "rows": rows, "ev": ev, "rtp": ev / BINGO_PRICE, "win": win}


def bingo_uniformity(draws: list[dict]) -> tuple[float, float, int] | None:
    """卡方適合度檢定:各號碼出現次數是否與『完全隨機』有差異。回傳 (卡方值, p 值, 球數)。"""
    n = len(draws)
    if n < 10:
        return None
    cnt: Counter = Counter()
    for d in draws:
        cnt.update(d["號碼"])
    expected = n * 20 / 80
    chi = sum((cnt.get(i, 0) - expected) ** 2 / expected for i in range(1, 81))
    df = 79  # Wilson-Hilferty 近似
    z = ((chi / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return chi, 0.5 * math.erfc(z / math.sqrt(2)), n * 20


LOTTO_PRICE = {"大樂透": 50, "威力彩": 100, "今彩539": 50}


def lotto_odds(kind: str) -> dict:
    """各獎項精確機率。回傳 {'rows': [(獎項, 條件, 機率)], 'any': 任一獎機率, 'price': 單注價格}"""
    rows: list[tuple[str, str, float]] = []
    if kind == "大樂透":  # 49 取 6 + 1 個特別號
        n, pk = 49, 6
        tot, rest = math.comb(n, pk), n - pk

        def p(k, s):
            if s:  # 特別號在我的號碼中
                return math.comb(pk, k) * (pk - k) * math.comb(rest, pk - k) / (tot * rest)
            return math.comb(pk, k) * math.comb(rest, pk - k) * (rest - (pk - k)) / (tot * rest)

        for name, cond, k, s in [("頭獎", "中6", 6, False), ("貳獎", "中5 + 特別號", 5, True),
                                 ("參獎", "中5", 5, False), ("肆獎", "中4 + 特別號", 4, True),
                                 ("伍獎", "中4", 4, False), ("陸獎", "中3 + 特別號", 3, True),
                                 ("柒獎", "中2 + 特別號", 2, True), ("普獎", "中3", 3, False)]:
            rows.append((name, cond, p(k, s)))
    elif kind == "威力彩":  # 第一區 38 取 6,第二區 8 取 1
        def p1(k):
            return math.comb(6, k) * math.comb(32, 6 - k) / math.comb(38, 6)

        for name, cond, k, m in [("頭獎", "6 + 第二區", 6, 1), ("貳獎", "中6", 6, 0), ("參獎", "5 + 第二區", 5, 1),
                                 ("肆獎", "中5", 5, 0), ("伍獎", "4 + 第二區", 4, 1), ("陸獎", "中4", 4, 0),
                                 ("柒獎", "3 + 第二區", 3, 1), ("捌獎", "2 + 第二區", 2, 1),
                                 ("玖獎", "中3", 3, 0), ("普獎", "1 + 第二區", 1, 1)]:
            rows.append((name, cond, p1(k) * (1 / 8 if m else 7 / 8)))
    elif kind == "今彩539":  # 39 取 5
        for name, cond, k in [("頭獎", "中5", 5), ("貳獎", "中4", 4), ("參獎", "中3", 3), ("肆獎", "中2", 2)]:
            rows.append((name, cond, math.comb(5, k) * math.comb(34, 5 - k) / math.comb(39, 5)))
    else:
        raise KeyError(kind)
    return {"rows": rows, "any": sum(r[2] for r in rows), "price": LOTTO_PRICE[kind]}


def lotto_wheel(kind: str, k: int) -> dict:
    """複式(多選幾個號碼全組合):注數、花費、頭獎機率。花費與機率成等比例增加,並不會更划算。"""
    pick = LOTTO_RULES[kind]["pick"]
    n = LOTTO_RULES[kind]["max_n"]
    combos = math.comb(k, pick)
    space = math.comb(n, pick) * (8 if kind == "威力彩" else 1)
    return {"combos": combos, "cost": combos * LOTTO_PRICE[kind], "p": combos / space}


# ════════════════════════════════════════════════════════════════════
#  資料層 ⑤-2 「AI 下注建議」:依預算與目標,用精確機率挑方案
# ════════════════════════════════════════════════════════════════════
TAX_THRESHOLD, TAX_RATE = 5000, 0.204  # 單注獎金超過 5,000 元:扣 20% 所得稅 + 0.4% 印花稅
BIG_PRIZE = 5000
MAX_BUDGET = 5000


def after_tax(prize: float) -> float:
    return prize * (1 - TAX_RATE) if prize > TAX_THRESHOLD else prize


def prob_total_at_least(dist: dict, n: int, need: int) -> tuple[float, float]:
    """n 注獨立,每注獎金(以固定單位計)分佈為 dist={單位數: 機率}。
    回傳 (總獎金恰好 = need-1 的機率, 總獎金 >= need 的機率),用精確動態規劃,不是估計。"""
    if need <= 0:
        return 0.0, 1.0
    state = [0.0] * (need + 1)
    state[0] = 1.0
    items = [(u, p) for u, p in dist.items() if p > 0]
    for _ in range(n):
        new = [0.0] * (need + 1)
        for t, pt in enumerate(state):
            if pt == 0.0:
                continue
            for u, pu in items:
                new[min(t + u, need)] += pt * pu
        state = new
    return state[need - 1], state[need]


def _tone(p: float, good_hi: float = 0.5, bad_lo: float = 0.1) -> str:
    return "good" if p >= good_hi else "bad" if p < bad_lo else "warn"


def _pct(p: float) -> str:
    if p >= 0.9995:
        return "99.9%+"
    if p < 1e-6:
        return f"約 1 / {1 / p:,.0f}" if p > 0 else "0%"
    if p < 0.001:
        return f"{p * 100:.4f}%"
    return f"{p * 100:.1f}%" if p >= 0.01 else f"{p * 100:.2f}%"


BINGO_GOALS = {"save": "🛡️ 長期少虧", "break": "🎯 最大機率回本", "big": "🚀 搏大獎(單注 5,000 元以上)"}


def bingo_advice(budget: int, goal: str = "save", per_draw: int = 1, rng=None) -> dict:
    rng = rng or random.SystemRandom()
    n = int(budget // BINGO_PRICE)
    if n < 1:
        raise ValueError("預算至少要 25 元(1 注)")
    if budget > MAX_BUDGET:
        raise ValueError(f"預算上限 {MAX_BUDGET:,} 元")
    rows = []
    for s in range(1, 11):
        o = bingo_odds(s)
        dist: dict = {}
        for r in o["rows"]:
            u = r["prize"] // BINGO_PRICE
            dist[u] = dist.get(u, 0.0) + r["p"]
        q_big = sum(r["p"] for r in o["rows"] if r["prize"] >= BIG_PRIZE)
        p_eq, p_gt = prob_total_at_least(dist, n, n + 1)  # 恰好回本 / 賺錢
        rows.append({
            "stars": s, "rtp": o["rtp"], "ev": o["ev"], "win": o["win"],
            "ev_after": sum(r["p"] * after_tax(r["prize"]) for r in o["rows"]),
            "p_any": 1 - (1 - o["win"]) ** n, "p_none": (1 - o["win"]) ** n,
            "p_even": p_eq + p_gt, "p_profit": p_gt,
            "p_big": 1 - (1 - q_big) ** n, "p_top": 1 - (1 - o["rows"][-1]["p"]) ** n,
        })
    key = {"save": lambda r: (r["rtp"], r["p_even"]), "break": lambda r: (r["p_even"], r["rtp"]),
           "big": lambda r: (r["p_big"], r["rtp"])}[goal]
    best = max(rows, key=key)
    s = best["stars"]

    seen, tickets = set(), []
    room = math.comb(80, s)
    while len(tickets) < n:
        nums = tuple(sorted(rng.sample(range(1, 81), s)))
        if nums in seen and len(seen) < room:
            continue
        seen.add(nums)
        tickets.append(nums)
    cost = n * BINGO_PRICE
    periods = -(-n // per_draw)

    why = {
        "save": f"{s} 星的長期回收率是 10 種星數裡最高的:每投注 100 元平均拿回 {best['rtp'] * 100:.1f} 元(稅前)。",
        "break": f"這筆預算買 {n} 注時,{s} 星讓「總獎金 ≥ 投入」的機率最高,有 {_pct(best['p_even'])}。",
        "big": f"{s} 星最有機會中到單注 5,000 元以上的獎:買 {n} 注約 {_pct(best['p_big'])}。",
    }[goal]
    reasons = [
        why,
        "選號:每個號碼被開出的機率完全相同,所以我用隨機分散的號碼,不會編造什麼『神號碼』。"
        "選哪幾個號碼,對勝算與期望值沒有任何影響。",
        f"投注節奏:每期買 {per_draw} 注,共 {periods} 期(賓果每 5 分鐘一期,約 {periods * 5} 分鐘買完)。"
        "分多期買不改變期望值,只是讓你隨時可以停手。",
    ]
    metrics = [
        ("至少中獎一次", _pct(best["p_any"]), "含拿回 25 元本金的小獎", _tone(best["p_any"], 0.9, 0.5)),
        ("拿回 ≥ 投入(不虧本)", _pct(best["p_even"]), "稅前,總獎金不低於花費", _tone(best["p_even"], 0.5, 0.2)),
        ("真正賺錢(拿回 > 投入)", _pct(best["p_profit"]), "你要的「勝算」就是這一格", "warn"),
        ("一毛都沒拿回", _pct(best["p_none"]), "所有注都沒中任何獎", "bad" if best["p_none"] > 0.3 else "warn"),
        ("平均拿回", f"{n * best['ev']:,.0f} 元", f"稅前;扣稅後約 {n * best['ev_after']:,.0f} 元", "warn"),
        ("中單注 5,000 元以上", _pct(best["p_big"]), "此類獎金須扣約 20.4% 稅", "warn"),
    ]
    lines = [f"【賓果 AI 建議】預算 {budget} 元 → {s} 星 × {n} 注 = {cost} 元,每期 {per_draw} 注、共 {periods} 期"]
    for i, t in enumerate(tickets, 1):
        lines.append(f"第{i}注 {s}星: " + " ".join(f"{x:02d}" for x in t))
    table = {
        "columns": ["星數", "每100元平均拿回", "至少中獎一次", "不虧本", "賺錢", "中5,000元以上"],
        "rows": [[f"{r['stars']} 星", f"{r['rtp'] * 100:.1f} 元", _pct(r["p_any"]), _pct(r["p_even"]),
                  _pct(r["p_profit"]), _pct(r["p_big"])] for r in rows],
        "best": s - 1,
    }
    verdict = (f"結論:{cost} 元平均只會拿回約 {n * best['ev']:,.0f} 元(稅前),平均虧 {cost - n * best['ev']:,.0f} 元。"
               f"賺到錢的機率 {_pct(best['p_profit'])},虧錢的機率 {_pct(1 - best['p_even'])}。"
               "我選的是這個預算下數學上最合理的方案,但它不會讓你『贏』——請把它當成娛樂費,只用輸得起的錢。")
    return {"title": f"🤖 AI 建議:{s} 星 × {n} 注({cost} 元)",
            "subtitle": f"目標:{BINGO_GOALS[goal]}  ·  每注 25 元", "reasons": reasons, "metrics": metrics,
            "tickets": [{"label": f"第 {i} 注 · {s} 星", "nums": list(t), "extra": None}
                        for i, t in enumerate(tickets, 1)],
            "table": table, "verdict": verdict, "copy_text": "\n".join(lines),
            "stats": best, "n": n, "cost": cost}


LOTTO_GOALS = {"safe": "🛡️ 少虧(只比較能精確算出期望值的彩種)", "freq": "🎯 想常常中獎",
               "jackpot": "🚀 頭獎機率最高", "billion": "👑 想中上億頭獎(大樂透/威力彩)"}
LOTTO_539_PRIZE = {5: 8_000_000, 4: 20_000, 3: 300, 2: 50}  # 今彩539:全部固定獎金


def lotto_539_stats() -> dict:
    """今彩539 單注:期望值(稅前 / 稅後)與以 50 元為單位的獎金分佈。"""
    dist: dict = {}
    ev = ev_after = 0.0
    for k in range(6):
        p = math.comb(5, k) * math.comb(34, 5 - k) / math.comb(39, 5)
        prize = LOTTO_539_PRIZE.get(k, 0)
        dist[prize // 50] = dist.get(prize // 50, 0.0) + p
        ev += p * prize
        ev_after += p * after_tax(prize)
    return {"dist": dist, "ev": ev, "rtp": ev / 50, "ev_after": ev_after, "rtp_after": ev_after / 50}


def lotto_advice(budget: int, goal: str = "safe", game: str = "auto", rng=None) -> dict:
    rng = rng or random.SystemRandom()
    if budget > MAX_BUDGET:
        raise ValueError(f"預算上限 {MAX_BUDGET:,} 元")
    info = {}
    for g in LOTTO_RULES:
        o = lotto_odds(g)
        price, n = o["price"], int(budget // o["price"])
        info[g] = {"game": g, "price": price, "n": n, "cost": n * price, "per_any": o["any"],
                   "per_top": o["rows"][0][2], "odds": o,
                   "p_any": 1 - (1 - o["any"]) ** n if n else 0.0,
                   "p_top": 1 - (1 - o["rows"][0][2]) ** n if n else 0.0}
    if game == "auto":
        cand = [g for g in info if info[g]["n"] >= 1 and (goal != "billion" or g != "今彩539")]
        if not cand:
            raise ValueError("預算不足:大樂透/今彩539 每注 50 元,威力彩 100 元")
        keyf = {"safe": lambda i: (i["game"] == "今彩539", i["p_any"]), "freq": lambda i: i["p_any"],
                "jackpot": lambda i: i["p_top"], "billion": lambda i: i["p_top"]}[goal]
        best = max((info[g] for g in cand), key=keyf)
    else:
        best = info[game]
        if best["n"] < 1:
            raise ValueError(f"預算不足:{game} 每注 {best['price']} 元")
    g, n, price = best["game"], best["n"], best["price"]
    mode = "random" if g == "今彩539" else "anti"
    tickets = generate_tickets(g, n, mode=mode, rng=rng)
    out_tickets = [{"label": f"第 {i} 注", "nums": t["nums"],
                    "extra": rng.randint(1, 8) if g == "威力彩" else None} for i, t in enumerate(tickets, 1)]
    cost = len(out_tickets) * price

    metrics = [
        ("至少中一個獎", _pct(best["p_any"]), "含小獎;小獎多半拿不回成本" if g != "今彩539" else "最低肆獎 50 元剛好回本",
         _tone(best["p_any"], 0.6, 0.2)),
        ("中頭獎", _pct(best["p_top"]), f"單注頭獎機率 1 / {1 / best['per_top']:,.0f}", "bad" if best["p_top"] < 0.001 else "warn"),
        ("一個獎都沒中", _pct((1 - best["per_any"]) ** n), "整筆預算全部槓龜", "bad" if (1 - best["per_any"]) ** n > 0.5 else "warn"),
    ]
    reasons = []
    st = None
    if g == "今彩539":
        st = lotto_539_stats()
        p_eq, p_gt = prob_total_at_least(st["dist"], n, n + 1)
        p_even, p_profit = p_eq + p_gt, p_gt
        metrics += [
            ("拿回 ≥ 投入(不虧本)", _pct(p_even), "稅前", _tone(p_even, 0.5, 0.2)),
            ("真正賺錢(拿回 > 投入)", _pct(p_profit), "你要的「勝算」就是這一格", "warn"),
            ("平均拿回", f"{n * st['ev']:,.0f} 元", f"稅前;扣稅後約 {n * st['ev_after']:,.0f} 元", "warn"),
            ("中貳獎(2 萬元)以上", _pct(1 - (1 - (math.comb(5, 4) * 34 + 1) / math.comb(39, 5)) ** n),
             "貳獎、頭獎須扣約 20.4% 稅", "warn"),
        ]
        reasons.append(f"今彩539 的四個獎項全是固定金額(800萬 / 2萬 / 300 / 50),所以是唯一能精確算出期望值的彩種:"
                       f"每投注 100 元平均拿回 {st['rtp'] * 100:.1f} 元(稅前),扣稅後約 {st['rtp_after'] * 100:.1f} 元。")
        reasons.append("固定獎金的彩種,選哪組號碼對期望值沒有影響,所以我用隨機分散的號碼。")
    else:
        reasons.append(f"{g} 的頭獎等是浮動獎金,每期金額不同,我無法替你精確計算期望值,只能給你精確的中獎機率。")
        reasons.append("浮動獎金會和其他中獎人平分,所以我用「避開大眾選號」:避開生日號、連號、等差直線等常見組合。"
                       "這不會提高中獎機率,只降低萬一中獎時要分獎的機會。")
        space = 1 / best["per_top"]
        ref = "、".join(f"頭獎 {j} 億 → 單注頭獎部分約 {j * 1e8 / space:.1f} 元" for j in (1, 3, 5))
        reasons.append(f"參考:每注成本 {price} 元;{ref}(尚未扣稅、也未考慮平分)。")
    why = {
        "safe": "你選擇「少虧」。" + ("在能精確計算的彩種裡,只有今彩539 的獎金結構完全已知。" if g == "今彩539" else ""),
        "freq": f"你想常常中獎:以這筆預算來比,{g} 的「至少中一個獎」機率最高({_pct(best['p_any'])})。",
        "jackpot": f"你要頭獎機率最高:同樣預算下,{g} 買到頭獎的機率最大({_pct(best['p_top'])})。",
        "billion": f"你想中上億頭獎:大樂透、威力彩裡,{g} 同樣預算的頭獎機率較高({_pct(best['p_top'])})。",
    }[goal]
    if game != "auto":
        why = f"你指定了 {g}。"
    reasons.insert(0, why)
    if g != "今彩539" and goal != "billion" and game == "auto":
        reasons.append("提醒:若你要的是『上億』頭獎,今彩539 的頭獎只有固定 800 萬;那就請把目標改成「想中上億頭獎」。")

    table = {
        "columns": ["彩種", "單注", "預算可買", "至少中一獎", "中頭獎", "期望回收率"],
        "rows": [[x["game"], f"{x['price']} 元", f"{x['n']} 注",
                  _pct(x["p_any"]) if x["n"] else "—", _pct(x["p_top"]) if x["n"] else "—",
                  (f"{lotto_539_stats()['rtp'] * 100:.1f}%(稅前)" if x["game"] == "今彩539" else "浮動獎金,無法精算")]
                 for x in info.values()],
        "best": list(info).index(g),
    }
    avg_line = (f"平均只會拿回約 {n * st['ev']:,.0f} 元(稅前),平均虧 {cost - n * st['ev']:,.0f} 元。"
                if st else "頭獎為浮動獎金,無法算出平均拿回多少;但小獎加起來通常遠低於成本。")
    verdict = (f"結論:{cost} 元買 {len(out_tickets)} 注 {g},{avg_line}"
               f"中任何獎的機率 {_pct(best['p_any'])},中頭獎的機率 {_pct(best['p_top'])}。"
               "我給的是這個預算下數學上最合理的方案,但它不會讓你『贏』——請把它當成娛樂費,只用輸得起的錢。")
    lines = [f"【{g} AI 建議】預算 {budget} 元 → {len(out_tickets)} 注 = {cost} 元"]
    for t in out_tickets:
        lines.append(t["label"].replace(" ", "") + ": " + " ".join(f"{x:02d}" for x in t["nums"]) +
                     (f" + {t['extra']:02d}" if t["extra"] else ""))
    return {"title": f"🤖 AI 建議:{g} × {len(out_tickets)} 注({cost} 元)",
            "subtitle": f"目標:{LOTTO_GOALS[goal]}  ·  每注 {price} 元", "reasons": reasons, "metrics": metrics,
            "tickets": out_tickets, "table": table, "verdict": verdict, "copy_text": "\n".join(lines),
            "game": g, "n": len(out_tickets), "cost": cost, "stats": best, "s539": st}


# ════════════════════════════════════════════════════════════════════
#  資料層 ⑤-2 AI 下注顧問:依預算計算方案與完整勝算
# ════════════════════════════════════════════════════════════════════
# 固定獎金(元)。沒列出的獎項為浮動獎金(視為遠高於一般預算)。資料來源:台灣彩券公告,2026/10 查證。
LOTTO_FIXED = {
    "今彩539": {"頭獎": 8_000_000, "貳獎": 20_000, "參獎": 300, "肆獎": 50},          # 全為固定獎金
    "大樂透": {"伍獎": 2000, "陸獎": 1000, "柒獎": 400, "普獎": 400},                 # 頭~肆獎浮動
    "威力彩": {"參獎": 150_000, "肆獎": 20_000, "伍獎": 4000, "陸獎": 800,
              "柒獎": 400, "捌獎": 200, "玖獎": 100, "普獎": 100},                    # 頭、貳獎浮動
}
PAYOUT_RATE = {"大樂透": 0.56, "威力彩": 0.55}          # 官方總獎金佔銷售額比例
TOP_PRIZE = {"今彩539": 8_000_000, "大樂透": 100_000_000, "威力彩": 200_000_000}  # 頭獎(保底)
GAME_PRICE = {"賓果": BINGO_PRICE, **LOTTO_PRICE}
GOAL_LABELS = {"ev": "回收最多、虧最少", "win": "最有機會賺到錢", "freq": "常常中小獎", "dream": "搏大獎"}
MAX_BUDGET = 10_000


BINGO_MULTS = [1, 2, 3, 4, 5, 10, 20, 50]   # 加倍投注 2~50 倍(1 = 不加倍)
BINGO_MAX_PERIODS = 12                        # 每張投注單最多連續 12 期(含當期)
BINGO_MAX_DRAWS = 400


def bingo_cap(stars: int, hits: int) -> int:
    """單期總獎金上限:10 星中 10 個為 1 億,其餘各獎項 1,000 萬。加倍後的獎金不會超過它。"""
    return 100_000_000 if (stars == 10 and hits == 10) else 10_000_000


def ticket_outcomes(game: str, stars: int = 0, mult: int = 1) -> list[tuple[float, int | None]]:
    """單期單組所有可能結果 [(機率, 獎金)]。獎金 None = 浮動獎金,0 = 沒中。機率總和為 1。
    賓果加倍:成本與獎金都乘以倍數(獎金受單期上限限制)。"""
    out: list[tuple[float, int | None]] = []
    if game == "賓果":
        out = [(r["p"], min(r["prize"] * mult, bingo_cap(stars, r["hits"])) if r["prize"] else 0)
               for r in bingo_odds(stars)["rows"]]
    else:
        fixed = LOTTO_FIXED[game]
        out = [(p, fixed.get(name)) for name, _c, p in lotto_odds(game)["rows"]]
    rest = 1 - sum(p for p, _ in out)
    if rest > 1e-12:
        out.append((rest, 0))
    return out


def ev_per_ticket(game: str, stars: int = 0, mult: int = 1) -> float:
    """單注(單期)的長期平均拿回金額。浮動獎金制(大樂透/威力彩)以官方總獎金率估算。"""
    if game == "賓果":
        return sum(p * (pay or 0) for p, pay in ticket_outcomes(game, stars, mult))
    if game == "今彩539":
        return sum(p * (pay or 0) for p, pay in ticket_outcomes(game))
    return PAYOUT_RATE[game] * LOTTO_PRICE[game]


def profit_probability(outcomes, price: int, n: int) -> tuple[float, float]:
    """買 n 注(各注獨立)後,總獎金『大於花費』的機率、與『大於等於花費』的機率。精確動態規劃。
    浮動獎金(None)視為遠大於花費。"""
    unit = price
    for _p, pay in outcomes:
        if pay:
            unit = math.gcd(unit, int(pay))
    cost_u = n * price // unit
    top = cost_u + 1  # 此格代表「總獎金 > 花費」
    single = [(p, top if pay is None else min(int(pay) // unit, top)) for p, pay in outcomes if p > 0]
    dp = [0.0] * (top + 1)
    dp[0] = 1.0
    for _ in range(n):
        new = [0.0] * (top + 1)
        for s_, ps in enumerate(dp):
            if ps < 1e-18:
                continue
            for p, u in single:
                new[min(s_ + u, top)] += ps * p
        dp = new
    return dp[top], dp[top] + dp[cost_u]


def plan_stats(game: str, stars: int, n: int, dp: bool = True, mult: int = 1) -> dict:
    """方案 = 同一玩法買 n 注(賓果為 n 期,每期加倍 mult 倍)。回傳完整勝算。"""
    mult = mult if game == "賓果" else 1
    price = GAME_PRICE[game] * mult
    outs = ticket_outcomes(game, stars, mult)
    p_any1 = sum(p for p, pay in outs if pay is None or pay > 0)
    p_gain1 = sum(p for p, pay in outs if pay is None or pay > price)
    if game == "賓果":
        top_p = bingo_odds(stars)["rows"][-1]["p"]
        top_prize = min(BINGO_PAYOUT[stars][stars] * mult, bingo_cap(stars, stars))
    else:
        top_p, top_prize = lotto_odds(game)["rows"][0][2], TOP_PRIZE[game]
    ev = ev_per_ticket(game, stars, mult)
    name = f"賓果 {stars} 星" + (f" ×{mult} 倍" if mult > 1 else "") if game == "賓果" else game
    res = {"game": game, "stars": stars, "n": n, "mult": mult, "price": price, "cost": n * price,
           "slips": math.ceil(n / BINGO_MAX_PERIODS) if game == "賓果" else 0,
           "p_any1": p_any1, "p_any": 1 - (1 - p_any1) ** n, "p_gain1": p_gain1,
           "p_gain": None, "p_even": None, "ev_each": ev, "ev_total": ev * n, "rtp": ev / price,
           "loss": n * (price - ev), "p_top1": top_p, "p_top": 1 - (1 - top_p) ** n, "top_prize": top_prize,
           "name": name, "mult_rows": []}
    if dp:
        res["p_gain"], res["p_even"] = profit_probability(outs, price, n)
    return res


def advisor_candidates(budget: int) -> list[tuple[str, int, int]]:
    """預算買得起的所有玩法 [(玩法, 星數, 注數)](賓果以不加倍計)。"""
    c: list[tuple[str, int, int]] = []
    nb = min(budget // BINGO_PRICE, BINGO_MAX_DRAWS)
    if nb >= 1:
        c += [("賓果", s, nb) for s in range(1, 11)]
    for g in ("今彩539", "大樂透", "威力彩"):
        n = min(budget // LOTTO_PRICE[g], 200)
        if n >= 1:
            c.append((g, 0, n))
    return c


def advisor_plan(budget: int, goal: str, game: str = "AI", mult="AI") -> tuple[dict, list[dict]] | None:
    """依預算與目標選出最佳方案;賓果會一併決定最佳加倍倍數(mult='AI')或使用指定倍數。
    回傳 (最佳方案, 比較用的各方案);best['mult_rows'] 為賓果各倍數的比較。"""
    cands = advisor_candidates(budget)
    if game != "AI":
        cands = [c for c in cands if c[0] == game]
    elif goal == "dream":  # 搏大獎時不考慮賓果(賓果最高才 500 萬)
        cands = [c for c in cands if c[0] != "賓果"]
    if mult != "AI" and BINGO_PRICE * mult > budget:
        if game == "賓果":
            raise ValueError(f"預算 {budget:,} 元不夠加到 {mult} 倍(賓果加到 {mult} 倍,每期要 {BINGO_PRICE * mult:,} 元)")
        cands = [c for c in cands if c[0] != "賓果"]
    if not cands:
        return None

    def options(_stars):  # 賓果可選的 (倍數, 期數)
        ms = [mult] if mult != "AI" else [m for m in BINGO_MULTS if BINGO_PRICE * m <= budget]
        return [(m, min(budget // (BINGO_PRICE * m), BINGO_MAX_DRAWS)) for m in ms]

    def pick_mult(stars):
        opts = options(stars)
        if len(opts) == 1 or goal == "freq":
            return opts[0]
        if goal == "dream":
            return opts[-1]
        scored = [(round(plan_stats("賓果", stars, n_, mult=m_)["p_gain"], 5), -m_, m_, n_) for m_, n_ in opts]
        _, _, m_, n_ = max(scored)
        return m_, n_

    if goal == "win":  # 淨賺機率最高:全面精確計算
        full = []
        for g, s_, n in cands:
            if g == "賓果":
                full += [plan_stats(g, s_, n_, mult=m_) for m_, n_ in options(s_)]
            else:
                full.append(plan_stats(g, s_, n))
        best = max(full, key=lambda st: (round(st["p_gain"], 6), st["rtp"]))
    else:
        stats = [plan_stats(g, s_, n, dp=False) for g, s_, n in cands]
        if goal == "ev":
            key = lambda st: (round(st["rtp"], 9), st["p_any"])
        elif goal == "freq":
            key = lambda st: (round(st["p_any"], 9), st["rtp"])
        elif game == "賓果":
            key = lambda st: (st["top_prize"], st["rtp"])
        else:  # 每投入 1 元,頭獎的期望值
            key = lambda st: (st["p_top1"] * st["top_prize"] / st["price"], st["rtp"])
        b0 = max(stats, key=key)
        if b0["game"] == "賓果":
            m_, n_ = pick_mult(b0["stars"])
            best = plan_stats("賓果", b0["stars"], n_, mult=m_)
        else:
            best = plan_stats(b0["game"], b0["stars"], b0["n"])

    # 比較表:最佳方案、賓果「回收最高 / 最常中」(不加倍)、再加上三種樂透
    keys = [(best["game"], best["stars"], best["n"], best["mult"])]
    bingo = [c for c in cands if c[0] == "賓果"]
    if bingo:
        bs = [plan_stats(g, s_, n, dp=False) for g, s_, n in bingo]
        for st in (max(bs, key=lambda x: x["rtp"]), max(bs, key=lambda x: x["p_any"])):
            k = (st["game"], st["stars"], st["n"], 1)
            if k not in keys and mult in ("AI", 1):
                keys.append(k)
    for g, s_, n in cands:
        if g != "賓果" and (g, s_, n, 1) not in keys:
            keys.append((g, s_, n, 1))
    rows = [best] + [plan_stats(g, s_, n, mult=m_) for g, s_, n, m_ in keys[1:]]
    if best["game"] == "賓果":
        mine = {k: v for k, v in best.items() if k != "mult_rows"}  # 避免循環參照
        best["mult_rows"] = [mine if m_ == best["mult"] else plan_stats("賓果", best["stars"], n_, mult=m_)
                             for m_, n_ in options(best["stars"])]
    return best, rows


def advisor_tickets(game: str, stars: int, n: int, rng=random) -> list[dict]:
    """依方案產生實際號碼。賓果號碼不影響勝算(固定同一組方便即可);樂透使用『避開大眾選號』。"""
    if game == "賓果":
        return [{"nums": sorted(rng.sample(range(1, 81), stars)), "second": None}]
    tickets = generate_tickets(game, n, mode="anti", rng=rng)
    for t in tickets:
        t["second"] = rng.randint(1, 8) if game == "威力彩" else None
    return tickets


def fmt_prob(p: float) -> str:
    """機率的易讀寫法:大的用百分比,小的用 1/x。"""
    if p <= 0:
        return "0"
    if p >= 0.01:
        return f"{p * 100:.1f}%(約 1/{1 / p:.1f})"
    if p >= 1e-4:
        return f"{p * 100:.3f}%(約 1/{1 / p:,.0f})"
    return f"1/{1 / p:,.0f}"


def advisor_reasons(best: dict, goal: str, game: str, rows: list[dict]) -> list[str]:
    """用白話說明『為什麼這樣建議』。"""
    out: list[str] = []
    bingo = best["game"] == "賓果"
    if goal == "ev":
        out.append(f"我用「長期回收率」選玩法:{best['name'].split(' ×')[0]} 每投注 100 元,長期平均拿回約 {best['rtp'] * 100:.0f} 元,"
                   f"是你這個預算買得起的所有玩法中最高的。")
        cmp = [f"{r['name']} {r['rtp'] * 100:.0f}%" for r in rows if r["name"] != best["name"]]
        if cmp:
            out.append("其他玩法的回收率:" + "、".join(cmp) + "。")
    elif goal == "win":
        out.append(f"我把賓果 1~10 星 × 各種加倍,加上三種樂透全部精確算過,「整份方案淨賺」機率最高的是 {best['name']}:"
                   f"{best['p_gain'] * 100:.1f}%。")
        out.append("要注意:淨賺機率高不代表比較划算——它的平均回收率只有 "
                   f"{best['rtp'] * 100:.0f}%,而且通常是「集中下注、贏了翻倍、輸了全輸」。")
    elif goal == "freq":
        out.append(f"我用「整份方案至少中一次獎的機率」選玩法:{best['name']} 買 {best['n']} {'期' if bingo else '注'},"
                   f"至少中一次的機率是 {best['p_any'] * 100:.1f}%。")
        out.append("但「中獎」不等於「賺錢」:" + (
            "賓果 2 星中 1 個只退還本金(25 元 × 倍數)。" if bingo else "小獎金額往往只有幾十到幾百元,不一定超過成本。") +
                   f"以這份方案來說,真正「拿回超過花費」的機率只有 {(best['p_gain'] or 0) * 100:.1f}%。")
    else:
        if game == "賓果":
            out.append(f"賓果最高獎是 10 星全中(機率約 1/{1 / bingo_odds(10)['rows'][-1]['p']:,.0f}),所以選 10 星並盡量加倍;"
                       "單期總獎金上限 1 億元,所以加到上限就不必再加。")
        else:
            l539, lbig, lpow = (lotto_odds(g)["rows"][0][2] for g in ("今彩539", "大樂透", "威力彩"))
            out.append(f"我用「每投入 1 元,頭獎的期望值」排序:今彩539 頭獎 800 萬、機率 1/{1 / l539:,.0f},"
                       f"是三種樂透中「每一塊錢最有機會拿到大獎」的。")
            out.append(f"若你想追億元級大獎:威力彩頭獎保底 2 億(機率 1/{1 / lpow:,.0f})、"
                       f"大樂透保底 1 億(機率 1/{1 / lbig:,.0f}),但機率低得多。")
        out.append(f"以這份預算,整份方案中頭獎的機率約 {fmt_prob(best['p_top'])}。")

    if bingo:
        m, n = best["mult"], best["n"]
        if len(best["mult_rows"]) > 1:
            rr = best["mult_rows"]
            top = max(rr, key=lambda r: r["p_gain"])
            out.append("關於「加倍」:加倍不會改變平均拿回(各倍數的平均拿回幾乎一樣),只改變結果的集中程度——"
                       f"贏的時候獎金乘以倍數,輸的時候也一次輸掉倍數。我把 {len(rr)} 種倍數都精確算過,"
                       f"淨賺機率最高的是 ×{top['mult']}({top['p_gain'] * 100:.1f}%),最低的是 "
                       f"×{min(rr, key=lambda r: r['p_gain'])['mult']}({min(r['p_gain'] for r in rr) * 100:.1f}%)。")
        if m > 1:
            out.append(f"我建議加 {m} 倍:每期 {best['price']} 元,共 {n} 期。")
        else:
            out.append("我建議不加倍:" + ("分散成多期,每一期都能重新決定要不要繼續,隨時可以停手。" if n > 1 else "只買一期。"))
        if n > BINGO_MAX_PERIODS:
            full, rest = divmod(n, BINGO_MAX_PERIODS)
            split = " + ".join([str(BINGO_MAX_PERIODS)] * full + ([str(rest)] if rest else []))
            out.append(f"投注單規定每張最多連買 {BINGO_MAX_PERIODS} 期(含當期),所以 {n} 期要分 {best['slips']} 張:{split} 期。")
    else:
        out.append("樂透號碼採「避開大眾選號」:不會提高中獎機率,只是避開生日號、連號、等差直線,"
                   "萬一中浮動獎金,較不容易和別人平分。")
    if best.get("p_gain") is not None and ((not bingo) or best["mult"] == 1):  # 注數與淨賺機率
        cap = BINGO_MAX_DRAWS if bingo else 200
        sizes = sorted({max(best["n"] // 4, 1), best["n"], min(best["n"] * 5, cap)})
        if len(sizes) > 1:
            parts = []
            for k in sizes:
                st = best if k == best["n"] else plan_stats(best["game"], best["stars"], k, mult=best["mult"])
                parts.append(f"買 {k} {'期' if bingo else '注'}({st['cost']:,} 元)→ {st['p_gain'] * 100:.1f}%")
            out.append("同樣玩法,不同注數的「淨賺」機率:" + "、".join(parts) + "。注數少時純看運氣、起伏很大;"
                       "但買得越多,結果越貼近「長期平均」——也就是虧損,淨賺機率最終會趨近 0。")
    return out


# ════════════════════════════════════════════════════════════════════
#  資料層 ⑥ 大頭照
# ════════════════════════════════════════════════════════════════════
PHOTO_SIZES = {
    "1 吋照片 (331 × 413 px)": (331, 413),
    "2 吋大頭照 - 護照/身分證 (413 × 531 px)": (413, 531),
    "2 吋半身照 - 健保卡/履歷 (496 × 555 px)": (496, 555),
}
SHEET_SIZE = (1800, 1200)  # 4×6 吋 @300dpi


def flatten_rgb(img):
    """轉 RGB;透明背景鋪成白色(直接 convert 會變黑底)。"""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")


def load_photo(path: str):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # 手機直拍照片自動轉正
    return flatten_rgb(img)


def crop_photo(img, size: tuple[int, int], cx: float = 0.5, cy: float = 0.4):
    """依目標比例置中裁切(cx/cy 可微調取景位置),不變形。"""
    return ImageOps.fit(img, size, Image.Resampling.LANCZOS, centering=(cx, cy))


def make_sheet(photo, sheet=SHEET_SIZE, gap: int = 14, margin: int = 20):
    """把同一張照片排滿 4×6 吋相紙(自動選橫式/直式較多者)。回傳 (排版圖, 張數)。"""
    pw, ph = photo.size
    best = None
    for W, H in (sheet, sheet[::-1]):
        cols = (W - 2 * margin + gap) // (pw + gap)
        rows = (H - 2 * margin + gap) // (ph + gap)
        if cols > 0 and rows > 0 and (best is None or cols * rows > best[0] * best[1]):
            best = (cols, rows, W, H)
    if best is None:
        return photo, 1
    cols, rows, W, H = best
    canvas = Image.new("RGB", (W, H), "white")
    gw, gh = cols * pw + (cols - 1) * gap, rows * ph + (rows - 1) * gap
    x0, y0 = (W - gw) // 2, (H - gh) // 2
    for r in range(rows):
        for c in range(cols):
            canvas.paste(photo, (x0 + c * (pw + gap), y0 + r * (ph + gap)))
    return canvas, cols * rows
