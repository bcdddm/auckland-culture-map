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
  # render:True → 用 Playwright 无头浏览器渲染（JS 站 / 反爬站），Actions 已装 chromium
  "aag":         [{"type":"html", "render":True, "url":"https://www.aucklandartgallery.com/whats-on/events", "selector":"a[href*='whats-on'], article, .card"},
                  {"type":"html", "render":True, "url":"https://www.aucklandartgallery.com/visit/exhibitions", "selector":"a[href*='exhibition'], article, .card"}],
  "gusfisher":   [{"type":"html", "url":"https://gusfishergallery.auckland.ac.nz/exhibitions/", "selector":"article, .et_pb_text, h1, h3"}],  # ✅ 2026-07-07 校准：/exhibitions/ 是静态HTML（WordPress/Divi），日期在 h3
  "artspace":    [{"type":"html", "url":"https://artspace-aotearoa.nz/exhibitions", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-07 校准：列表页静态HTML，日期直接在链接文本里
  "michaellett": [{"type":"html", "url":"https://lett-thomas.com/", "selector":"a[href*='/exhibition/']"}],  # ✅ 2026-07-07 校准：已改名 Lett Thomas，静态HTML
  "objectspace": [{"type":"html", "url":"https://www.objectspace.org.nz/exhibitions/", "selector":"a[href*='/exhibitions/'], h2, h3"}],  # ✅ 2026-07-07 校准：/whats-on/ 不存在，正确列表页静态可抓
  "teuru":       [{"type":"html", "url":"https://teuru.org.nz/pages/exhibitions-events", "selector":"a[href*='/products/'], article"}],  # ✅ 2026-07-07 校准：静态HTML，事件在 /products/ 链接里
  "corban":      [{"type":"html", "url":"https://ceac.org.nz/activities", "selector":"article, .event, .card, a[href*='/exhibitions/'], a[href*='/events/']"}],  # ✅ 2026-07-07 校准：现域名 ceac.org.nz，静态HTML（corbanestate.org.nz 已失效）
  "library":     [{"type":"html", "render":True, "url":"https://www.aucklandlibraries.govt.nz/Pages/events.aspx", "selector":".event, article, li"}],
  "unity":       [{"type":"html", "render":True, "url":"https://unitybooks.co.nz/", "selector":"a[href*='event'], article, .card"}],
  "timeout":     [{"type":"html", "render":True, "url":"https://www.timeout.co.nz/", "selector":"a[href*='event'], article, .card"}],
  "poetrylive":  [],   # ✅ 2026-07-10 校准：每周二 19:00 @ Thirty Nine（39 Ponsonby Rd，thirtynine.co.nz/event-list）→ 规则生成；Facebook 源撞登录墙已弃
  "townhall":    [{"type":"html", "render":True, "url":"https://www.aucklandlive.co.nz/whats-on", "selector":"article, .card, .event-tile, a[href*='event']"}],  # Auckland Live 页面带 JSON-LD，渲染后优先读结构化数据
  # UTR 每场馆 iCal：https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=<ID>（比 HTML 稳定）
  # 2026-07-07 已确认：Whammy=316，Powerstation=105（venue 119 是 Safari Lounge，勿用）
  "whammy":      [{"type":"ical", "url":"https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=316"}],   # ✅ 2026-07-07 确认：UTR vid 316 = Whammy Bar（另有 3991 Backroom / 6373 Double Whammy）
  "powerstation":[{"type":"ical", "url":"https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=105"}],   # ✅ 2026-07-07 确认：UTR vid 105 = The Powerstation
  "studioone":   [{"type":"html", "url":"https://www.studioone.org.nz/exhibitions/", "selector":"article, .event, .card, h3"}],  # ✅ 2026-07-07 校准：/whats-on/ 404，展讯在 /exhibitions/（静态WP）
  "britomart":   [],   # 固定每周六 → 规则生成
  "lacigale":    [],   # 固定周六/周日 → 规则生成
  "avondale":    [],   # 固定周日 → 规则生成
  # ---- 中南 / 东南 / 东区 / 激流岛 / 北岸 ----
  "tetuhi":      [{"type":"html", "url":"https://tetuhi.art/current-exhibitions/", "selector":"a[href*='/exhibition/']"}],  # ✅ 2026-07-07 校准：静态HTML，展讯是 /exhibition/ 链接，日期在链接文本
  "mangere":     [{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/mangere-arts-centre.html", "selector":"article, .card, li"}],
  "freshgallery":[{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/fresh-gallery-otara.html", "selector":"article, .card, li"}],
  "nathan":      [{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/nathan-homestead.html", "selector":"article, .card, li"}],
  "pah":         [{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/pah-homestead.html", "selector":"article, .card, li"}],
  "teoro":       [{"type":"html", "url":"https://www.eventfinda.co.nz/venue/te-oro-auckland", "selector":"article, .card, a[href*='/whatson/']"}],  # ✅ 2026-07-07 校准：teoro.org.nz DNS 失效，改用 Eventfinda 场馆页（服务端渲染，带 JSON-LD）
  "uxbridge":    [{"type":"html", "render":True, "url":"https://uxbridge.org.nz/whats-on/", "selector":"article, .card, .event"}],
  "waihekegallery": [{"type":"html", "render":True, "url":"https://www.waihekeartgallery.org.nz/", "selector":"article, .card, .event, a[href*='exhibition']"}],
  "depot":       [{"type":"html", "url":"https://depotartspace.co.nz/whats-on/", "selector":"article, .card, .event"}],
  "otaramarket": [],   # 固定周六 → 规则生成
  "ostend":      [],   # 固定周六 → 规则生成
  # ---- 北岸 & Hibiscus Coast ----
  "northart":    [{"type":"html", "url":"https://www.northartgallery.net/current-exhibitions", "selector":"article, .card, .event, a[href*='exhibition']"}],  # ✅ 2026-07-07 校准：官网迁至 northartgallery.net（Squarespace）；旧域名证书失效
  # ✅ gowlangsford 用 Artlogic CMS，静态HTML，展览卡片是 a[href*='/exhibitions/']（下方已配置）
  # ✅ 2026-07-07 复查：gusfisher /exhibitions/ 实为静态HTML，可直接抓（上方已改 URL）
  "lakehouse":   [{"type":"html", "render":True, "url":"https://www.lakehousearts.org.nz/", "selector":"article, .card, .event, a[href*='event']"}],
  "mairangi":    [{"type":"html", "url":"https://mairangiarts.co.nz/exhibitions/", "selector":"article, .card, .event"}],
  "estuary":     [{"type":"html", "render":True, "url":"https://www.estuaryarts.org/exhibitions", "selector":"article, .card, .event, h2"}],  # ✅ 2026-07-10 校准：Wix 站拒脚本 UA（RemoteDisconnected），改 /exhibitions + render
  "pumphouse":   [{"type":"html", "url":"https://pumphouse.co.nz/whats-on/", "selector":"article, .card, .event"}],
  # ---- 西区 / Rodney / 南区 社区艺术中心 ----
  "upstairs":    [{"type":"html", "url":"https://www.upstairs.org.nz/events", "selector":"article, .eventlist-event, .card, .event"}],  # ✅ 2026-07-10 校准：新官网 upstairs.org.nz（Squarespace 静态，lopdell.org.nz 拒连已弃）
  "mccahon":     [{"type":"html", "url":"https://www.mccahonhouse.org.nz/", "selector":"article, .card, .event"}],
  "tetoiuku":    [{"type":"html", "url":"https://www.tetoiuku.org.nz/", "selector":"a[href*='whats-on'], article, .card"}],  # ✅ 2026-07-07 校准：现域名 tetoiuku.org.nz（portageceramicstrust.org.nz DNS 失效）
  "helensville": [{"type":"html", "url":"https://www.artcentrehelensville.org.nz/", "selector":"article, .card, .event"}],
  "papakura":    [{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/papakura-art-gallery.html", "selector":"article, .card, li"}],
  "franklin":    [{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/franklin-arts-centre.html", "selector":"article, .card, li"}],
  # ---- Dealer 画廊（官网结构各异，开幕信息统一走 ArtNow 兜底更省事）----
  "gowlangsford": [{"type":"html", "url":"https://gowlangsfordgallery.co.nz/exhibitions/", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-07 校准
  "starkwhite":  [{"type":"html", "url":"https://starkwhite.co.nz/", "selector":"a[href*='/exhibition/']"}],  # ✅ 2026-07-07 校准：静态HTML
  "tworooms":    [{"type":"html", "url":"https://tworooms.co.nz/exhibitions/", "selector":"article, .exhibition, li"}],
  "sanderson":   [{"type":"html", "url":"https://www.sanderson.co.nz/exhibitions", "selector":"article, .exhibition, li"}],
  "foenander":   [], "coastalsigns": [], "bergman": [],
  "melanieroger": [{"type":"html", "render":True, "url":"https://melanierogergallery.com/exhibitions/", "selector":"article, .card, a[href*='/exhibitions/']"}],  # ✅ 2026-07-13 配源：拒脚本 UA → render
  "ivananthony": [{"type":"html", "render":True, "url":"https://www.ivananthony.com/", "selector":"article, .card, a[href*='exhibition']"}],  # ✅ 2026-07-13 配源
  "artis": [], "flagstaff": [], "artbysea": [], "vivian": [],
  # ---- 2026-07-11 批量配源：表演/音乐/博物馆/画廊优先（书店暂缓）----
  # 博物馆
  "museum":      [{"type":"html", "render":True, "url":"https://www.aucklandmuseum.com/visit/whats-on", "selector":"a[href*='whats-on'], article, .card"}],
  "maritime":    [{"type":"html", "render":True, "url":"https://www.maritimemuseum.co.nz/whats-on", "selector":"article, .card, a[href*='event']"}],
  "motat":       [{"type":"html", "render":True, "url":"https://www.motat.nz/whats-on/", "selector":"article, .card, a[href*='event']"}],
  # 剧场（Auckland Live 系走 scrape_aucklandlive 路由，勿单配 civic/aotea/brucemason）
  "qtheatre":    [{"type":"html", "render":True, "url":"https://www.qtheatre.co.nz/whats-on", "selector":"a[href*='show'], article, .card"}],
  "basement":    [{"type":"html", "render":True, "url":"https://basementtheatre.co.nz/whats-on/", "selector":"a[href*='show'], article, .card"}],
  "asbwaterfront": [{"type":"html", "render":True, "url":"https://www.atc.co.nz/asb-waterfront-theatre-events", "selector":"a[href*='/whats-on/'], article, .card"}],  # ✅ 2026-07-13 校准：旧域名拒连，节目页在 ATC 官网
  "tepou":       [{"type":"html", "render":True, "url":"https://tepoutheatre.nz/whats-on/", "selector":"article, .card"}],
  "titirangitheatre": [{"type":"html", "render":True, "url":"https://www.titirangitheatre.co.nz/", "selector":"article, .card, li"}],
  "artworkstheatre": [{"type":"html", "render":True, "url":"https://www.artworkstheatre.org.nz/", "selector":"article, .card, a[href*='event']"}],
  "howicklittle": [{"type":"html", "render":True, "url":"https://hlt.nz/", "selector":"article, .card, a[href*='show']"}],
  "dolphin":     [{"type":"html", "render":True, "url":"https://dolphintheatre.org.nz/", "selector":"article, .card"}],
  "harlequin":   [{"type":"html", "render":True, "url":"https://harlequintheatre.co.nz/", "selector":"article, .card"}],
  "playhouse":   [{"type":"html", "render":True, "url":"https://www.playhouse.nz/", "selector":"article, .card, a[href*='show'], a[href*='event']"}],  # ✅ 2026-07-13 校准：新域名 playhouse.nz（旧域名 DNS 失效）
  "rosecentre":  [{"type":"html", "render":True, "url":"https://rosecentre.co.nz/", "selector":"article, .card, a[href*='event']"}],
  "theatreworks": [{"type":"html", "render":True, "url":"https://theatreworks.nz/", "selector":"article, .card, a[href*='show']"}],  # ✅ 2026-07-13 校准：新域名 theatreworks.nz（.co.nz 是达尼丁另一家公司）
  "companytheatre": [{"type":"html", "render":True, "url":"https://www.companytheatre.co.nz/", "selector":"article, .card"}],
  "centrestage": [{"type":"html", "render":True, "url":"https://centrestagetheatre.co.nz/", "selector":"article, .card, a[href*='show']"}],
  "hawkins":     [{"type":"html", "render":True, "url":"https://www.hawkinstheatre.co.nz/", "selector":"article, .card, a[href*='event']"}],
  "papakuratheatre": [],   # 只有 Facebook → 每周任务手动补
  # 影院：只抓特别放映/节展，日常排片噪音大 → 暂不配源，待做"特殊场次"过滤后再开
  "academy": [], "capitol": [], "vic": [], "bridgeway": [],
  # 音乐
  "sparkarena":  [{"type":"html", "render":True, "url":"https://www.sparkarena.co.nz/events", "selector":"article, .card, a[href*='event']"}],
  "tuningfork":  [{"type":"html", "render":True, "url":"https://www.tuningfork.co.nz/", "selector":"article, .card, a[href*='event']"}],
  "galatos":     [{"type":"html", "render":True, "url":"https://galatos.co.nz/", "selector":"article, .card, a[href*='event']"}],
  "neckofthewoods": [{"type":"html", "render":True, "url":"https://neckofthewoods.co.nz/", "selector":"article, .card, a[href*='event']"}],
  "anthology":   [{"type":"ical", "url":"https://www.undertheradar.co.nz/feeds/showsIcalVenues.php?vid=4688"}],  # ✅ 2026-07-13 校准：anthology.co.nz 证书失效；UTR vid 4688 = Anthology Lounge（官网 anthologykroad.com 无排期页）
  "mothership":  [{"type":"html", "render":True, "url":"https://www.themothership.co.nz/", "selector":"article, .card"}],
  "bigfan":      [{"type":"html", "render":True, "url":"https://www.bigfan.co.nz/whats-on", "selector":"article, .card, a[href*='event']"}],
  "stmatthews":  [{"type":"html", "render":True, "url":"https://www.stmatthews.org.nz/whats-on/", "selector":"article, .card, li"}],
  "holytrinity": [{"type":"html", "render":True, "url":"https://www.holy-trinity.org.nz/events", "selector":"article, .card, li"}],
  # 画廊/大学空间/雕塑园
  "rmgallery":   [{"type":"html", "render":True, "url":"https://rm.org.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "tautai":      [{"type":"html", "render":True, "url":"https://tautai.org/", "selector":"article, .card, a[href*='exhibition']"}],
  "stpaulst":    [{"type":"html", "render":True, "url":"https://stpaulst.aut.ac.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "window":      [{"type":"html", "render":True, "url":"https://windowgallery.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "whitespace":  [{"type":"html", "render":True, "url":"https://www.whitespace.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "allpress":    [{"type":"html", "url":"https://www.eventfinda.co.nz/venue/allpress-studio-auckland", "selector":"article, .card, a[href*='/whatson/']"}],  # ✅ 2026-07-13 校准：allpressstudio.com DNS 失效，官网无活动页，用 Eventfinda 场馆页
  "intlart":     [{"type":"html", "render":True, "url":"https://www.internationalartcentre.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "parnellgallery": [{"type":"html", "render":True, "url":"https://www.parnellgallery.co.nz/exhibitions/", "selector":"article, .card, a[href*='exhibition']"}],
  "blackdoor":   [{"type":"html", "render":True, "url":"https://www.blackdoorgallery.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "trishclark":  [{"type":"html", "render":True, "url":"https://trishclark.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "masterworks": [{"type":"html", "render":True, "url":"https://masterworksgallery.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "timmelville": [{"type":"html", "render":True, "url":"https://www.timmelville.com/", "selector":"article, .card, a[href*='exhibition']"}],  # ✅ 2026-07-13 校准：现域名 timmelville.com
  "webbs":       [{"type":"html", "render":True, "url":"https://www.webbs.co.nz/auctions", "selector":"article, .card, a[href*='auction']"}],
  "artobject":   [{"type":"html", "render":True, "url":"https://www.artandobject.co.nz/", "selector":"article, .card, a[href*='auction']"}],
  "twng":        [{"type":"html", "url":"https://ngutukaka.nz/exhibitions", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-13 校准：新官网 ngutukaka.nz（Statamic 静态，日期在链接文本）；twng.aut.ac.nz DNS 失效
  "foxjensen":   [{"type":"html", "render":True, "url":"https://foxjensengallery.com/", "selector":"article, .card, a[href*='exhibition']"}],
  "season":      [{"type":"html", "render":True, "url":"https://seasonaotearoa.com/", "selector":"article, .card, a[href*='exhibition']"}],
  "annamiles":   [{"type":"html", "render":True, "url":"https://annamilesgallery.com/", "selector":"article, .card, a[href*='exhibition']"}],
  "fhe":         [{"type":"html", "render":True, "url":"https://fhegalleries.com/", "selector":"article, .card, a[href*='exhibition']"}],
  "turua":       [{"type":"html", "render":True, "url":"https://www.turuagallery.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "railwayst":   [{"type":"html", "render":True, "url":"https://www.railwaystreetstudios.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "suite":       [{"type":"html", "render":True, "url":"https://suite.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "satellite2":  [{"type":"html", "render":True, "url":"https://satellite2.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "artselect":   [{"type":"html", "render":True, "url":"https://www.artselect.gallery/", "selector":"article, .card"}],
  "antoinettegodkin": [{"type":"html", "render":True, "url":"https://antoinettegodkin.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "westcoastgallery": [{"type":"html", "render":True, "url":"https://www.westcoastgallery.co.nz/", "selector":"article, .card"}],
  "brickbay":    [{"type":"html", "render":True, "url":"https://www.brickbaysculpture.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],
  "sculptureum": [{"type":"html", "render":True, "url":"https://www.sculptureum.nz/", "selector":"article, .card"}],
  "connellsbay": [], "elam": [],   # 预约制/学期制 → 每周任务按学期手动补
  # 工作坊
  "nathan":      [{"type":"html", "render":True, "url":"https://www.aucklandcouncil.govt.nz/en/arts-culture-heritage/arts/art-centres-galleries-theatres/nathan-homestead.html", "selector":"article, .card, li"}],
  "helensville": [{"type":"html", "render":True, "url":"https://www.artcentrehelensville.org.nz/", "selector":"article, .card"}],
  "kumeuarts":   [{"type":"html", "render":True, "url":"https://www.kumeuarts.org/", "selector":"article, .card, a[href*='event']"}],
  "mccahon":     [{"type":"html", "render":True, "url":"https://www.mccahonhouse.org.nz/", "selector":"article, .card"}],
  "tetoiuku":    [{"type":"html", "render":True, "url":"https://www.tetoiuku.org.nz/", "selector":"article, .card, li"}],
  "teoro":       [{"type":"html", "render":True, "url":"https://www.eventfinda.co.nz/venue/te-oro-auckland", "selector":"article, .card, a[href*='/whatson/']"}],  # ✅ 2026-07-13：teoro.org.nz DNS 失效已移除，只留 Eventfinda 场馆页
  "library":     [{"type":"html", "render":True, "url":"https://www.aucklandlibraries.govt.nz/Pages/events.aspx", "selector":".event, article, li"}],
  "jonathangrant": [{"type":"html", "url":"https://jgg.co.nz/", "selector":"article, .card, a[href*='exhibition']"}],  # ✅ 2026-07-13 校准：现域名 jgg.co.nz
  "winecellar":  [{"type":"html", "render":True, "url":"https://www.winecellar.co.nz/", "selector":"article, .card, a[href*='gig'], a[href*='event']"}],
  # 影院（academy/capitol/vic/bridgeway）日常排片刻意不抓；节展季由每周任务经 Eventfinda 手动补
  # ---- 2026-07-13 本周新配：书店/文学 ----
  "womensbookshop": [{"type":"html", "url":"https://womensbookshop.co.nz/pages/1311-NewsandEvents", "selector":"article, .card, p, li, h3"}],  # ✅ 2026-07-13 配源：News and Events 页（静态）
  "michaelking": [{"type":"html", "url":"https://writerscentre.org.nz/workshops/", "selector":"article, .card, h3, li"},
                  {"type":"html", "url":"https://writerscentre.org.nz/events/", "selector":"article, .card, h3, li"}],  # ✅ 2026-07-13 配源：WordPress 静态
  # ---- 2026-07-20 本周新配：dealer 画廊收尾 ----
  "artis":       [{"type":"html", "url":"https://www.artisgallery.co.nz/exhibitions/current/", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-20 配源：Artlogic CMS 静态（同 gowlangsford），日期在链接文本
  "foenander":   [{"type":"html", "url":"https://foenandergalleries.co.nz/exhibitions", "selector":"a[href*='/exhibitions/']"}],  # ✅ 2026-07-20 配源：Artlogic CMS 静态
  "coastalsigns":[{"type":"html", "url":"https://coastal-signs.net/", "selector":"p, figcaption, li"}],  # ✅ 2026-07-20 配源：Kirby 静态站，首页列当季展讯；命中率不稳 → manual_events 兜底
  "flagstaff":   [{"type":"html", "url":"https://www.flagstaff.nz/pages/events", "selector":"article, .card, p, h2, h3, li"}],  # ✅ 2026-07-20 配源：Shopify 服务端渲染；官网 footer 地址 6 Victoria Rd（VENUES 已修正）
  "artbysea":    [{"type":"html", "render":True, "url":"https://www.artbythesea.co.nz/", "selector":"article, .card, p, h2, h3, li"}],  # ✅ 2026-07-20 配源：Wix JS 站；画廊已迁址 Takapuna 162 Hurstmere Rd（VENUES 已修正）
  "vivian":      [{"type":"html", "render":True, "url":"https://www.thevivian.co.nz/", "selector":"article, .card, p, h2, h3"}],  # ✅ 2026-07-20 配源：Matakana，冬季周五–周一开放（TripAdvisor 标 CLOSED 系误标，官网在营）
  # "bergman" 不配源：奥克兰空间 2022–2026 运营已于 2026 年结束（Cook Islands News 报道），主画廊回迁拉罗汤加；地图上保留灰色
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

def fetch_html(src):
    """render:True 的源用 Playwright 无头浏览器渲染（JS 站）；否则普通请求。"""
    if src.get("render"):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                pg = b.new_page(user_agent=UA["User-Agent"])
                try:
                    pg.goto(src["url"], wait_until="networkidle", timeout=30000)
                except Exception:
                    # 2026-07-20：networkidle 常被长轮询/统计脚本挡住而超时（上周 9 例）→
                    # 退回 domcontentloaded + 固定等待 4s，仍拿渲染后的 DOM，而不是降级普通请求
                    pg.goto(src["url"], wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(4000)
                html = pg.content()
                b.close()
                return html
        except ImportError:
            print("[warn] playwright 未安装，降级为普通请求", file=sys.stderr)
        except Exception as e:
            print(f"[warn] playwright 渲染失败({e})，降级为普通请求", file=sys.stderr)
    r = requests.get(src["url"], headers=UA, timeout=30)
    r.raise_for_status()
    return r.text

def extract_jsonld_events(venue, soup, base):
    """优先读 schema.org Event 结构化数据——标题/日期/价格/链接机器可读，远比正则可靠。"""
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        flat = []
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and "@graph" in d:
                flat += [x for x in d["@graph"] if isinstance(x, dict)]
            elif isinstance(d, dict):
                flat.append(d)
        for d in flat:
            types = d.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if not any("Event" in str(x) for x in types):
                continue
            try:
                sd = datetime.date.fromisoformat(str(d.get("startDate", ""))[:10])
            except Exception:
                continue
            if not (TODAY <= sd <= HORIZON):
                continue
            name = (d.get("name") or "").strip()
            if not name:
                continue
            item = {"venue": venue, "title": name[:110], "date": str(sd),
                    "kind": classify(name), "url": d.get("url") or base,
                    "desc": re.sub(r"<[^>]+>", "", str(d.get("description") or ""))[:180]}
            img = d.get("image")
            if isinstance(img, list) and img: img = img[0]
            if isinstance(img, dict): img = img.get("url")
            if isinstance(img, str) and img.startswith("http"): item["img"] = img
            offers = d.get("offers")
            o = (offers[0] if isinstance(offers, list) and offers else offers) or {}
            if isinstance(o, dict):
                p = str(o.get("price", ""))
                if p in ("0", "0.0", "0.00"): item["price"] = "free"
                elif p: item["price"] = "paid"
            out.append(item)
    return out

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
    soup = BeautifulSoup(fetch_html(src), "html.parser")
    # 第一优先级：JSON-LD 结构化数据，命中即返回
    ld = extract_jsonld_events(venue, soup, src["url"])
    if ld:
        return ld
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

AKL_LIVE_ROUTES = {   # Auckland Live 共享节目页 → 按 location.name 分派到场馆
    "civic":      ["civic"],
    "aotea":      ["aotea", "kiri te kanawa", "herald"],
    "townhall":   ["town hall"],
    "brucemason": ["bruce mason"],
}
def _akl_parse_jsonld(soup, base):
    """从一个 soup 里提取 JSON-LD Event 并按 location.name 路由；供列表页与详情页共用。"""
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        flat = []
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and "@graph" in d:
                flat += [x for x in d["@graph"] if isinstance(x, dict)]
            elif isinstance(d, dict):
                flat.append(d)
        for d in flat:
            types = d.get("@type", ""); types = types if isinstance(types, list) else [types]
            if not any("Event" in str(x) for x in types):
                continue
            try:
                sd = datetime.date.fromisoformat(str(d.get("startDate", ""))[:10])
            except Exception:
                continue
            if not (TODAY <= sd <= HORIZON):
                continue
            loc = d.get("location")
            loc = (loc[0] if isinstance(loc, list) and loc else loc) or {}
            locname = str(loc.get("name", "")).lower() if isinstance(loc, dict) else str(loc).lower()
            vid = None
            for v, keys in AKL_LIVE_ROUTES.items():
                if any(k in locname for k in keys):
                    vid = v; break
            if not vid:
                continue
            name = (d.get("name") or "").strip()
            if not name:
                continue
            item = {"venue": vid, "title": name[:110], "date": str(sd), "kind": "gig",
                    "url": d.get("url") or base,
                    "desc": re.sub(r"<[^>]+>", "", str(d.get("description") or ""))[:180]}
            img = d.get("image")
            if isinstance(img, list) and img: img = img[0]
            if isinstance(img, dict): img = img.get("url")
            if isinstance(img, str) and img.startswith("http"): item["img"] = img
            out.append(item)
    return out

def scrape_aucklandlive():
    """渲染 aucklandlive.co.nz/whats-on 读 JSON-LD 路由到多个场馆。
    2026-07-13 备援：What's On 列表是客户端渲染、JSON-LD 时有时无——若列表页拿到 0 条，
    则从渲染后的列表页 + 官网首页收集 /show/、/event/ 详情链接，逐页（普通请求）读 JSON-LD。"""
    src = {"render": True, "url": "https://www.aucklandlive.co.nz/whats-on"}
    soup = BeautifulSoup(fetch_html(src), "html.parser")
    out = _akl_parse_jsonld(soup, src["url"])
    if not out:
        links = set()
        def collect(sp):
            for a in sp.select("a[href*='/show/'], a[href*='/event/']"):
                h = a.get("href") or ""
                if h.startswith("/"): h = "https://www.aucklandlive.co.nz" + h
                if h.startswith("https://www.aucklandlive.co.nz/"): links.add(h.split("?")[0].rstrip("/"))
        collect(soup)
        try:
            collect(BeautifulSoup(fetch_html({"render": True, "url": "https://www.aucklandlive.co.nz/"}), "html.parser"))
        except Exception:
            pass
        seen = set()
        for u in sorted(links)[:30]:
            try:
                sp = BeautifulSoup(fetch_html({"url": u}), "html.parser")   # 详情页 JSON-LD 服务端渲染，普通请求即可
            except Exception:
                continue
            for it in _akl_parse_jsonld(sp, u):
                key = (it["venue"], it["title"][:40], it["date"])
                if key in seen: continue
                seen.add(key)
                out.append(it)
    print(f"[ok]   aucklandlive-router: {len(out)} events")
    return out

def weekly_rule_events():
    """固定周期的集市：直接按规则生成未来31天。"""
    rules = [  # (venue, weekday 一=0…日=6, title, zh, kind, url)
        ("britomart",   5, "Britomart Saturday Markets", "Britomart 周六集市", "market", "#"),
        ("lacigale",    5, "La Cigale French Market (Sat)", "La Cigale 法式集市（周六）", "market", "#"),
        ("lacigale",    6, "La Cigale French Market (Sun)", "La Cigale 法式集市（周日）", "market", "#"),
        ("avondale",    6, "Avondale Sunday Markets", "Avondale 周日集市", "market", "#"),
        ("otaramarket", 5, "Ōtara Flea Market", "Ōtara 周六集市", "market", "#"),
        ("ostend",      5, "Ostend Market (Waiheke)", "Ostend 集市（激流岛，周六）", "market", "#"),
        ("poetrylive",  1, "Poetry Live — open mic (every Tuesday)", "Poetry Live 开放麦（每周二）", "reading", "https://www.thirtynine.co.nz/event-list"),  # 2026-07-10 确认：Thirty Nine, 39 Ponsonby Rd, 19:00
    ]
    out = []
    d = TODAY
    while d <= HORIZON:
        for venue, wd, title, zh, kind, url in rules:
            if d.weekday() == wd:
                out.append({"venue": venue, "title": title, "zh": zh, "date": str(d), "kind": kind, "url": url})
        d += datetime.timedelta(days=1)
    return out

OG_RE1 = re.compile(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)', re.I)
OG_RE2 = re.compile(r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image', re.I)

def enrich_images(items, cap_total=90):
    """列表页通常没有 JSON-LD 图——逐条请求活动详情页，提取 og:image（普通请求即可，og 标签在原始 HTML 里）。"""
    n = 0
    for e in items:
        if n >= cap_total:
            break
        if e.get("img") or e.get("kind") == "market":
            continue
        last = e.get("end") or e.get("date")
        if not last or last < str(TODAY):        # 历史条目不补图
            continue
        u = e.get("url") or ""
        if not u.startswith("http") or "facebook.com" in u or "instagram.com" in u:
            continue
        n += 1
        try:
            r = requests.get(u, headers=UA, timeout=12)
            if r.status_code != 200:
                continue
            m = OG_RE1.search(r.text) or OG_RE2.search(r.text)
            if m and m.group(1).startswith("http"):
                e["img"] = m.group(1)
        except Exception:
            continue
    got = sum(1 for e in items if e.get("img"))
    print(f"[ok]   image-enrich: fetched {n} detail pages, {got} items now have images")

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
    try:
        items += scrape_aucklandlive()       # Civic/Aotea/市政厅/Bruce Mason 共享路由
    except Exception as e:
        print(f"[warn] aucklandlive-router: {e}", file=sys.stderr)
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
    enrich_images(items)
    items.sort(key=lambda e: (e["date"], e["venue"]))
    payload = {"generated": str(TODAY), "sample": False, "items": items}
    OUT.write_text(
        "// 由 scraper/scrape.py 自动生成 — 请勿手改（手动条目放 scraper/manual_events.json）\n"
        "window.EVENTS = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8")
    # 纯 JSON 副本：供外部软件/API 消费（https://bcdddm.github.io/auckland-culture-map/events.json）
    (OUT.parent / "events.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[done] {len(items)} events -> {OUT}")

if __name__ == "__main__":
    main()
