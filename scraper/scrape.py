#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
奥克兰文化贴纸地图 · 活动抓取脚本
- 逐场馆抓取 events 页面（HTML / iCal），提取"未来 31 天内"的活动
- 合并 manual_events.json（手动补充：只发 Instagram 的小场馆）
- 输出 ../events.js（window.EVENTS = {...}）

依赖: pip install requests beautifulsoup4 python-dateutil
用法: python scraper/scrape.py

⚠️ 各场馆网站结构会变，选择器是"尽力而为"，跑失败的场馆会打印警告并跳过，
   不影响其他场馆。每次失败都可以只修 SOURCES 里那一条。
"""
import json, re, sys, datetime, pathlib
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dparse

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT.parent / "events.js"
MANUAL = ROOT / "manual_events.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-NZ,en;q=0.9"}
TODAY = datetime.date.today()
HORIZON = TODAY + datetime.timedelta(days=31)

# ---------------------------------------------------------------
# 每个场馆的数据源。type:
#   html  — 抓页面，selector 选出活动卡片，在卡片文本里解析日期
#   ical  — 标准 iCal 日历订阅
# 修某个场馆时只改这一条即可。url 失效就换成该场馆最新的 events 页。
# ---------------------------------------------------------------
SOURCES = {
  "aag":         [{"type":"html", "url":"https://www.aucklandartgallery.com/whats-on", "selector":"a[href*='whats-on'], article, .card"}],
  "gusfisher":   [{"type":"html", "url":"https://gusfishergallery.auckland.ac.nz/exhibitions/", "selector":"article, .et_pb_text, h1, h3"}],  # ✅ 2026-07-07 校准：/exhibitions/ 是静态HTML（WordPress/Divi），日期在 h3
  "artspace":    [{"type":"html", "url":"https://artspace-aotearoa.nz/exhibitions", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-07 校准：列表页静态HTML，日期直接在链接文本里
  "michaellett": [{"type":"html", "url":"https://lett-thomas.com/", "selector":"a[href*='/exhibition/']"}],  # ✅ 2026-07-07 校准：已改名 Lett Thomas，静态HTML
  "objectspace": [{"type":"html", "url":"https://www.objectspace.org.nz/exhibitions/", "selector":"a[href*='/exhibitions/'], h2, h3"}],  # ✅ 2026-07-07 校准：/whats-on/ 不存在，正确列表页静态可抓
  "teuru":       [{"type":"html", "url":"https://teuru.org.nz/pages/exhibitions-events", "selector":"a[href*='/products/'], article"}],  # ✅ 2026-07-07 校准：静态HTML，事件在 /products/ 链接里
  "corban":      [{"type":"html", "url":"https://www.corbanestate.org.nz/whats-on/", "selector":"article, .event, .card"}],  # 域名修正（cebarts.org.nz DNS 失效）
  "library":     [{"type":"html", "url":"https://www.aucklandlibraries.govt.nz/Pages/events.aspx", "selector":".event, article, li"}],
  "unity":       [{"type":"html", "url":"https://unitybooksauckland.co.nz/events", "selector":"article, .event, .card"}],
  "timeout":     [{"type":"html", "url":"https://www.timeout.co.nz/events", "selector":"article, .event, .card"}],
  "poetrylive":  [{"type":"html", "url":"https://www.facebook.com/poetrylive/", "selector":"article"}],   # 常年周二；抓不到就走 manual
  "townhall":    [{"type":"html", "url":"https://www.aucklandlive.co.nz/whats-on?venue=auckland-town-hall", "selector":"article, .card, .event-tile"}],
  # UTR 每场馆 iCal：https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=<ID>（比 HTML 稳定）
  # 2026-07-07 已确认：Whammy=316，Powerstation=105（venue 119 是 Safari Lounge，勿用）
  "whammy":      [{"type":"ical", "url":"https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=316"}],   # ✅ 2026-07-07 确认：UTR vid 316 = Whammy Bar（另有 3991 Backroom / 6373 Double Whammy）
  "powerstation":[{"type":"ical", "url":"https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=105"}],   # ✅ 2026-07-07 确认：UTR vid 105 = The Powerstation
  "studioone":   [{"type":"html", "url":"https://studioone.org.nz/whats-on/", "selector":"article, .event, .card"}],
  "britomart":   [],   # 固定每周六 → 规则生成
  "lacigale":    [],   # 固定周六/周日 → 规则生成
  "avondale":    [],   # 固定周日 → 规则生成
  # ---- 中南 / 东南 / 东区 / 激流岛 / 北岸 ----
  "tetuhi":      [{"type":"html", "url":"https://tetuhi.art/current-exhibitions/", "selector":"a[href*='/exhibition/']"}],  # ✅ 2026-07-07 校准：静态HTML，展讯是 /exhibition/ 链接，日期在链接文本
  "mangere":     [{"type":"html", "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/mangere-arts-centre.html", "selector":"article, .card, li"}],
  "freshgallery":[{"type":"html", "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/fresh-gallery-otara.html", "selector":"article, .card, li"}],
  "nathan":      [{"type":"html", "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/nathan-homestead.html", "selector":"article, .card, li"}],
  "pah":         [{"type":"html", "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/pah-homestead.html", "selector":"article, .card, li"}],
  "teoro":       [{"type":"html", "url":"https://www.teoro.org.nz/whats-on", "selector":"article, .card, .event"}],
  "uxbridge":    [{"type":"html", "url":"https://uxbridge.org.nz/whats-on/", "selector":"article, .card, .event"}],
  "waihekegallery": [{"type":"html", "url":"https://www.waihekeartgallery.org.nz/whats-on/", "selector":"article, .card, .event"}],
  "depot":       [{"type":"html", "url":"https://depotartspace.co.nz/whats-on/", "selector":"article, .card, .event"}],
  "otaramarket": [],   # 固定周六 → 规则生成
  "ostend":      [],   # 固定周六 → 规则生成
  # ---- 北岸 & Hibiscus Coast ----
  "northart":    [{"type":"html", "url":"https://northart.co.nz/", "selector":"article, .card, .event"}],  # ✅ 静态HTML；⚠️ 证书只对无 www 域名有效
  # ✅ gowlangsford 用 Artlogic CMS，静态HTML，展览卡片是 a[href*='/exhibitions/']（下方已配置）
  # ✅ 2026-07-07 复查：gusfisher /exhibitions/ 实为静态HTML，可直接抓（上方已改 URL）
  "lakehouse":   [{"type":"html", "url":"https://www.lakehousearts.org.nz/whats-on", "selector":"article, .card, .event"}],
  "mairangi":    [{"type":"html", "url":"https://mairangiarts.co.nz/exhibitions/", "selector":"article, .card, .event"}],
  "estuary":     [{"type":"html", "url":"https://www.estuaryarts.org/", "selector":"article, .card, .event"}],
  "pumphouse":   [{"type":"html", "url":"https://pumphouse.co.nz/whats-on/", "selector":"article, .card, .event"}],
  # ---- 西区 / Rodney / 南区 社区艺术中心 ----
  "upstairs":    [{"type":"html", "url":"https://www.lopdell.org.nz/upstairs-gallery", "selector":"article, .card, .event"}],
  "mccahon":     [{"type":"html", "url":"https://www.mccahonhouse.org.nz/", "selector":"article, .card, .event"}],
  "tetoiuku":    [{"type":"html", "url":"https://www.portageceramicstrust.org.nz/", "selector":"article, .card, li"}],
  "helensville": [{"type":"html", "url":"https://www.artcentrehelensville.org.nz/", "selector":"article, .card, .event"}],
  "papakura":    [{"type":"html", "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/papakura-art-gallery.html", "selector":"article, .card, li"}],
  "franklin":    [{"type":"html", "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/franklin-arts-centre.html", "selector":"article, .card, li"}],
  # ---- Dealer 画廊（官网结构各异，开幕信息统一走 ArtNow 兜底更省事）----
  "gowlangsford": [{"type":"html", "url":"https://gowlangsfordgallery.co.nz/exhibitions/", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-07 校准
  "starkwhite":  [{"type":"html", "url":"https://starkwhite.co.nz/", "selector":"a[href*='/exhibition/']"}],  # ✅ 2026-07-07 校准：静态HTML
  "tworooms":    [{"type":"html", "url":"https://tworooms.co.nz/exhibitions/", "selector":"article, .exhibition, li"}],
  "sanderson":   [{"type":"html", "url":"https://www.sanderson.co.nz/exhibitions", "selector":"article, .exhibition, li"}],
  "foenander":   [], "melanieroger": [], "ivananthony": [], "rmgallery": [], "tautai": [],
  "stpaulst":    [], "window": [], "coastalsigns": [], "bergman": [], "whitespace": [],
  "allpress":    [], "artis": [], "intlart": [], "parnellgallery": [],
  "flagstaff":   [], "artbysea": [], "vivian": [],
}
# 提示：ArtNow.NZ (https://artnow.nz/exhibitions) 是全国画廊开幕的聚合源，
# 之后可以加一个 artnow 适配器按场馆名反查，作为各画廊官网抓取的兜底。

KIND_WORDS = [
  ("opening",  r"opening|preview|launch|开幕|首展"),
  ("reading",  r"poet|poem|reading|author|book\s?launch|writers?|诗|朗读|签售"),
  ("workshop", r"workshop|class|course|studio|make|craft|工作坊|课"),
  ("market",   r"market|集市|市集"),
  ("gig",      r"gig|concert|live|orchestra|band|dj|音乐会|演出"),
]
DATE_RE = re.compile(
  r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{0,4}"
  r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s*\d{0,4}"
  r"|\d{4}-\d{2}-\d{2})", re.I)

def classify(text):
    t = text.lower()
    for kind, pat in KIND_WORDS:
        if re.search(pat, t):
            return kind
    return "opening"

def parse_date(text):
    m = DATE_RE.search(text)
    if not m: return None
    try:
        d = dparse.parse(m.group(0), default=datetime.datetime(TODAY.year, TODAY.month, TODAY.day), dayfirst=True).date()
        if d < TODAY - datetime.timedelta(days=300):  # 没写年份被解析成过去 → 加一年
            d = d.replace(year=d.year + 1)
        return d
    except Exception:
        return None

def scrape_html(venue, src):
    out = []
    r = requests.get(src["url"], headers=UA, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    for node in soup.select(src["selector"])[:60]:
        text = " ".join(node.get_text(" ", strip=True).split())
        if len(text) < 12: continue
        d = parse_date(text)
        if not d or not (TODAY <= d <= HORIZON): continue
        # 年份合法性：文本里写明的年份全部早于今年 → 是旧展归档，跳过（防止 2024 展被误标为今年）
        yrs = [int(y) for y in re.findall(r"\b(20[0-3]\d)\b", text)]
        if yrs and max(yrs) < TODAY.year: continue
        title = text[:110]
        link = node.get("href") or (node.find("a")["href"] if node.find("a") and node.find("a").get("href") else src["url"])
        if link and link.startswith("/"):
            from urllib.parse import urljoin; link = urljoin(src["url"], link)
        key = (title[:40], str(d))
        if key in seen: continue
        seen.add(key)
        price = "free" if re.search(r"free entry|free admission|entry is free|\bfree\b", text, re.I) \
                else ("koha" if re.search(r"\bkoha\b", text, re.I) else None)
        item = {"venue": venue, "title": title, "date": str(d), "kind": classify(text),
                "url": link, "desc": text[:180]}
        if price: item["price"] = price
        out.append(item)
    return out

def scrape_ical(venue, src):
    out = []
    r = requests.get(src["url"], headers=UA, timeout=30); r.raise_for_status()
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", r.text, re.S):
        mS = re.search(r"SUMMARY:(.+)", ev); mD = re.search(r"DTSTART[^:]*:(\d{8})", ev)
        if not (mS and mD): continue
        d = datetime.datetime.strptime(mD.group(1), "%Y%m%d").date()
        if TODAY <= d <= HORIZON:
            t = mS.group(1).strip()
            k = classify(t)
            if k == "opening": k = "gig"   # iCal 源（undertheradar）都是演出
            out.append({"venue": venue, "title": t, "date": str(d), "kind": k, "url": src["url"]})
    return out

def weekly_rule_events():
    """固定周期的集市：直接按规则生成未来31天。"""
    rules = [  # (venue, weekday 一=0…日=6, title, zh)
        ("britomart",   5, "Britomart Saturday Markets", "Britomart 周六集市"),
        ("lacigale",    5, "La Cigale French Market (Sat)", "La Cigale 法式集市（周六）"),
        ("lacigale",    6, "La Cigale French Market (Sun)", "La Cigale 法式集市（周日）"),
        ("avondale",    6, "Avondale Sunday Markets", "Avondale 周日集市"),
        ("otaramarket", 5, "Ōtara Flea Market", "Ōtara 周六集市"),
        ("ostend",      5, "Ostend Market (Waiheke)", "Ostend 集市（激流岛，周六）"),
    ]
    out = []
    d = TODAY
    while d <= HORIZON:
        for venue, wd, title, zh in rules:
            if d.weekday() == wd:
                out.append({"venue": venue, "title": title, "zh": zh, "date": str(d), "kind": "market", "url": "#"})
        d += datetime.timedelta(days=1)
    return out

def load_history():
    """保留上一版 events.js 里已结束的条目（卡片"上次活动"依赖它），每场馆最多留 5 条。"""
    if not OUT.exists():
        return []
    m = re.search(r"window\.EVENTS\s*=\s*(\{.*\})\s*;", OUT.read_text(encoding="utf-8"), re.S)
    if not m:
        return []
    try:
        prev = json.loads(m.group(1)).get("items", [])
    except Exception:
        print("[warn] 旧 events.js 含注释/非纯JSON，历史条目跳过（首次生成后即为纯JSON）", file=sys.stderr)
        return []
    past, per_venue = [], {}
    for e in sorted(prev, key=lambda x: x.get("end") or x.get("date") or "", reverse=True):
        last = e.get("end") or e.get("date")
        if not last or datetime.date.fromisoformat(last) >= TODAY:
            continue
        if per_venue.get(e["venue"], 0) >= 5:
            continue
        per_venue[e["venue"]] = per_venue.get(e["venue"], 0) + 1
        past.append(e)
    return past

def main():
    items = []
    for venue, srcs in SOURCES.items():
        for src in srcs:
            try:
                got = scrape_ical(venue, src) if src["type"] == "ical" else scrape_html(venue, src)
                items += got
                print(f"[ok]   {venue}: {len(got)} events")
            except Exception as e:
                print(f"[warn] {venue}: {e}", file=sys.stderr)
    items += weekly_rule_events()
    hist = load_history()
    seen_keys = {(e["venue"], e["title"][:40], e["date"]) for e in items}
    items += [e for e in hist if (e["venue"], e["title"][:40], e["date"]) not in seen_keys]
    print(f"[ok]   history: kept {len(hist)} past items")
    if MANUAL.exists():
        # 策展母本：全量并入（含双语、展览、历史），页面自行按日期归类显示；按 (venue,title前40,date) 去重
        manual = json.loads(MANUAL.read_text(encoding="utf-8"))
        keys = {(e["venue"], e["title"][:40], e["date"]) for e in items}
        added = [e for e in manual if (e["venue"], e["title"][:40], e["date"]) not in keys]
        items += added
        print(f"[ok]   manual/curated: merged {len(added)}")
    items.sort(key=lambda e: (e["date"], e["venue"]))
    payload = {"generated": str(TODAY), "sample": False, "items": items}
    OUT.write_text(
        "// 由 scraper/scrape.py 自动生成 — 请勿手改（手动条目放 scraper/manual_events.json）\n"
        "window.EVENTS = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8")
    print(f"[done] {len(items)} events -> {OUT}")

if __name__ == "__main__":
    main()
