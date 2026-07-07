# 奥克兰文化贴纸地图 · Auckland Culture Sticker Map

黑白卫星地图上贴满彩色建筑贴纸：美术馆、书店、诗歌之夜、音乐现场、工作坊、集市。
点击贴纸——反光扫过、贴纸被撕下、一张纸质卡片落下，展示该场馆本周/本月的活动。
有活动 = 彩色贴纸；没活动 = 灰色。

《外省人觀察 / The Province Review》的独立栏目页。

## 文件

| 文件 | 作用 |
|---|---|
| `index.html` | 整个页面（Leaflet 地图 + 61 张手绘 SVG 贴纸 + 全部交互），零构建。覆盖大奥克兰全域：中区、西区（含 Titirangi/Henderson/Helensville）、中南、东南、东区、南区（Papakura/Pukekohe）、北岸、Hibiscus Coast、Rodney（Matakana）与激流岛 |
| `events.js` | 活动数据，由脚本生成。**当前是示例数据**（`sample: true`） |
| `scraper/scrape.py` | 抓取各场馆活动页 → 生成 `events.js` |
| `scraper/manual_events.json` | 手动补充条目（只发 Instagram 的小场馆放这里） |
| `.github/workflows/update-events.yml` | 每周一早上自动跑抓取并 commit |

## 部署（GitHub Pages）

1. 新建 GitHub 仓库，把本文件夹全部内容 push 上去。
2. 仓库 Settings → Pages → Source 选 `main` 分支根目录 → Save。
3. 一分钟后页面在 `https://<用户名>.github.io/<仓库名>/`。
4. Settings → Actions → General → Workflow permissions 选 **Read and write**（让机器人能 commit `events.js`）。

## 嵌入 Wix（三种方式，可叠加）

**不要**把代码贴进"嵌入代码 HTML"组件（会被 Wix 过滤，交互会坏——博客更新流程.md 第三节的教训）。

**方式 A · 站内独立页面（推荐）**
1. Wix 编辑器：菜单和页面 → 新建页面（如"地图 Map"）。
2. 添加元素 (+) → 嵌入代码 → **嵌入网站（Embed a Site / iframe）**。
3. 填 GitHub Pages 地址 `https://<用户名>.github.io/<仓库名>/`。
4. 尺寸：宽度拉满页面；桌面高度建议 **900–1000px**；手机版高度 **620px** 左右。
   手机版如显示局促，可在手机编辑器里隐藏 iframe，放一个大按钮链接到全屏页。
5. 发布。以后数据自动更新，此页面永不用再动。

**方式 B · 博客文章内嵌**：写一期博客介绍这张地图，正文里同样用「嵌入网站」组件放 iframe（高度 700px 即可），文末附全屏链接。

**方式 C · 导航外链**：导航栏加一个链接直接指向 GitHub Pages 地址，新标签页全屏打开，体验最好。

三种方式都不需要每周维护：数据更新发生在 GitHub 侧，Wix 只是个窗口。

## 数据更新

- 自动：GitHub Actions 每周一 06:00 NZST 跑一次；也可在 Actions 页手动 Run workflow。
- 抓取失败的场馆只打 warning 不中断，修 `scrape.py` 里 `SOURCES` 对应那一条即可（换 url 或选择器）。
- 固定周期集市（Britomart 周六、Avondale 周日、La Cigale 周末）按规则自动生成，不用抓。
- 第一次上线前先本地跑一遍 `python scraper/scrape.py` 检查各场馆输出，把抓不到的补进 `manual_events.json`。

## 加/改场馆

1. `index.html` 里 `VENUES` 数组加一条（经纬度、名称、类别）。
2. `FACADES` 里画一张 76×60 的立面 SVG（参考现有 18 张的写法）。
3. `scraper/scrape.py` 的 `SOURCES` 加数据源。

## 底图与版权

左下角可切换三个底图（均转灰度）：
- **Esri World Imagery**（默认，最清晰；免费使用需保留署名）
- **EOX Sentinel-2 cloudless**（开源卫星图，CC BY-NC-SA 4.0，非商业；10m 分辨率，放大会糊）
- **OpenStreetMap**（开源街道图，ODbL，遵守 [tile 使用政策](https://operations.osmfoundation.org/policies/tiles/)）

贴纸为按各建筑真实立面绘制的原创插画。
