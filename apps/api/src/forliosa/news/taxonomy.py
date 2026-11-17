"""The fixed vocabulary of news tags (產品負責人 2026-11-17: 入庫時用 Haiku 貼主題與類股標籤).

Every stored headline gets up to three **themes**, a few **sectors** and up to five **related stocks**
(:mod:`forliosa.news.tagging`). The model may only pick from the lists below: the JSON schema it answers in names
them, and anything else is dropped. Tags are stored by id (``news_tags.value``), never by label, so a label can be
reworded without touching stored rows.

Versioning
----------
:data:`TAXONOMY_VERSION` is stored with each tagged headline (``news_tag_state.taxonomy_version``). Bump it when an id
is added, removed or changes meaning: the tagging job then tags the headlines of its window (``NEWS_TAGGING_DAYS``)
again, oldest first, and replaces their tags. Older rows outside the window keep their tags until they are deleted
with the headline (30 days); an id that no longer exists is never shown or searched.

Sectors
-------
* Taiwan: the official TWSE / TPEx 產業別 (``company_profiles.industry_code``, :data:`opendata.INDUSTRY_CODES`),
  stored as the code (``"24"``) so a tag joins the company profiles and the sector indices directly. Left out: 綜合
  (19), 其他業 (20), 管理股票 (80) and 存託憑證 (91) — they say nothing about what a story is about.
* US: twelve GICS-like sectors (GICS itself is licensed), the eleven sectors plus semiconductors on their own (they
  matter most to Taiwan's supply chain). :func:`us_sector` gives a company's: :data:`US_SECTOR_BY_TICKER` for the
  companies the sector hints name and the large ones whose SEC SIC code says otherwise (SIC 7370 holds Alphabet and
  Meta next to IT services, 7389 Visa and PayPal next to business services), else :func:`us_sector_for_sic`.
  ``tests/news/test_tagging.py`` checks that every company a hint names gets that hint's sector, so the prompt never
  says two things about one company.

The prompt names the sector of each stock a headline is stored under (the Taiwan company's 官方產業別, a US company's
:func:`us_sector`; :meth:`forliosa.news.tagging.Catalog.sector`); the model picks it when the story is about that
company. :data:`THEMES_OF_SECTOR`: a headline given an industry's sector also gets that industry's theme (金融 for a
bank's news), added by the server, so a search by theme finds what the model filed only under the sector.
"""

from __future__ import annotations

from dataclasses import dataclass

from forliosa.marketdata.opendata import INDUSTRY_CODES

TAXONOMY_VERSION = 1
MAX_THEMES = 3
MAX_SECTORS = 3
MAX_SYMBOLS = 5

KINDS = ("theme", "sector", "symbol")
RELATIONS = ("mentioned", "supply_chain", "peer")
RELATION_LABELS = {"mentioned": "點名", "supply_chain": "供應鏈", "peer": "同業"}


@dataclass(frozen=True)
class Tag:
    id: str
    label: str
    hint: str = ""  # what belongs here (shown to the model)


THEMES: tuple[Tag, ...] = (
    # industries and technologies (across Taiwan and the US)
    Tag("ai_server", "AI 伺服器", "AI 伺服器、GPU 與 AI 晶片、資料中心、算力、雲端業者的 AI 支出"),
    Tag("advanced_process", "先進製程", "晶圓代工、先進製程（3 奈米、2 奈米）、晶圓產能與報價"),
    Tag("advanced_packaging", "先進封裝", "CoWoS、SoIC、HBM 封裝、封測"),
    Tag("semi_equipment", "半導體設備", "半導體設備與材料、廠務工程"),
    Tag("memory", "記憶體", "DRAM、NAND Flash、HBM、記憶體報價與供需"),
    Tag("pc_phone", "PC／手機", "筆電、PC、手機、平板、穿戴裝置等消費性電子"),
    Tag("networking", "網通／光通訊", "交換器、網通設備、光通訊、矽光子、CPO、5G"),
    Tag("pcb_components", "PCB／零組件", "PCB、載板、被動元件、連接器、散熱、電源供應器"),
    Tag("software_cloud", "雲端／軟體", "雲端服務、軟體、網路平台、資安、生成式 AI 的應用與 AI 公司"),
    Tag("ev_auto", "電動車", "電動車、汽車與零組件、自駕、車用電子"),
    Tag("space_satellite", "低軌衛星／太空", "低軌衛星、火箭、太空產業"),
    Tag("robotics", "機器人", "機器人、人形機器人、工廠自動化"),
    Tag("defense_drone", "國防／無人機", "國防預算、軍購、軍工、無人機"),
    Tag("power_grid", "重電／電網", "重電、電網、變壓器、電力供應、電價"),
    Tag("green_energy", "綠能／儲能", "太陽能、風電、儲能、減碳"),
    Tag("biotech", "生技醫療", "新藥、醫材、藥廠、醫療服務"),
    Tag("shipping", "航運", "貨櫃、散裝、航空公司、物流、運價"),
    Tag("materials", "原物料", "鋼鐵、塑化、水泥、紡織、金屬與大宗商品價格"),
    Tag("oil_energy", "油價／能源", "原油、天然氣、油價、能源公司"),
    Tag("finance", "金融", "銀行、壽險、金控、券商的經營、獲利與系統（金融股的新聞都選）"),
    Tag("property", "營建／房市", "房地產、營建、房價、房貸、REITs"),
    Tag("consumer", "消費／觀光", "零售、餐飲、食品、觀光、內需消費"),
    Tag("crypto", "加密貨幣", "比特幣、加密貨幣、穩定幣、加密資產 ETF"),
    # macro and markets
    Tag("trade_tariffs", "關稅／貿易", "關稅、貿易談判、出口管制、晶片禁令、制裁"),
    Tag("rates_fx", "利率／匯率", "Fed 與央行、升降息、公債殖利率、新台幣與美元等匯率"),
    Tag("economy", "經濟數據", "GDP、通膨、就業、PMI、外銷訂單、景氣，國際機構的經濟預測"),
    Tag("geopolitics", "地緣政治", "兩岸、美中關係、戰爭與軍事衝突，影響市場的國際政治事件"),
    Tag("market_moves", "大盤行情", "台股、美股等大盤指數的漲跌、盤勢、類股輪動、市值排名"),
    # company events
    Tag("monthly_revenue", "營收公告", "公司公布月營收、季營收的數字"),
    Tag("earnings", "財報／法說", "季報、年報、獲利、EPS、法說會、財測"),
    Tag("shareholder_returns", "股利／庫藏股", "現金股利、股票股利、除權息、庫藏股、減資"),
    Tag("mna_investment", "併購／投資", "併購、入股、合資、策略合作、轉投資"),
    Tag("capacity_capex", "擴產／資本支出", "建廠、擴產、資本支出、海外設廠"),
    Tag("regulation_legal", "法規／訴訟", "法規、主管機關、監管、罰款、訴訟、檢調、勞資爭議"),
    Tag("incidents", "事故／資安", "系統當機、停電、火災、工安、資安攻擊、產品召回"),
    Tag("management", "人事", "董事長、執行長等經營層的任免、接班、經營權（一般員工、勞資不算）"),
    Tag("fund_flows", "資金流向／ETF", "外資與三大法人買賣超、大戶與基金的買賣、融資融券、ETF、國安基金"),
    Tag("analyst_views", "評等／目標價", "券商、外資的評等、目標價與研究報告"),
    Tag("ipo_financing", "上市／籌資", "IPO、新股上市櫃、現金增資、可轉債"),
    Tag("price_moves", "個股異動", "標題寫到個股股價的漲停、跌停、大漲、重挫、創新高，或注意股、處置股"),
)

_TW_SECTORS_LEFT_OUT = frozenset({"19", "20", "80", "91"})
TW_SECTORS: tuple[Tag, ...] = tuple(Tag(code, label) for code, label in INDUSTRY_CODES.items()
                                    if code not in _TW_SECTORS_LEFT_OUT)
# The companies each US sector's hint names: (ticker, name in the hint). They are all in US_SECTOR_BY_TICKER.
US_SECTOR_EXAMPLES: dict[str, tuple[tuple[str, str], ...]] = {
    "us_semis": (("NVDA", "Nvidia"), ("AMD", "AMD"), ("AVGO", "Broadcom"), ("MU", "Micron"),
                 ("AMAT", "Applied Materials")),
    "us_tech": (("AAPL", "Apple"), ("MSFT", "Microsoft"), ("ORCL", "Oracle"), ("DELL", "Dell")),
    "us_comm": (("GOOGL", "Alphabet"), ("META", "Meta"), ("NFLX", "Netflix"), ("T", "AT&T")),
    "us_consumer_disc": (("AMZN", "Amazon"), ("TSLA", "Tesla"), ("NKE", "Nike")),
    "us_staples": (("WMT", "Walmart"), ("COST", "Costco"), ("KO", "Coca-Cola")),
    "us_health": (("LLY", "Eli Lilly"), ("PFE", "Pfizer"), ("UNH", "UnitedHealth")),
    "us_financials": (("JPM", "JPMorgan"), ("V", "Visa")),
    "us_industrials": (("BA", "Boeing"), ("CAT", "Caterpillar")),
    "us_energy": (("XOM", "Exxon Mobil"), ("CVX", "Chevron")),
}


def _us(sector_id: str, label: str, hint: str) -> Tag:
    names = "、".join(name for _, name in US_SECTOR_EXAMPLES.get(sector_id, ()))
    return Tag(sector_id, label, f"{hint}：{names}" if names else hint)


US_SECTORS: tuple[Tag, ...] = (
    _us("us_semis", "美股半導體", "半導體與半導體設備"),
    _us("us_tech", "美股科技", "軟體、電腦與硬體、IT 服務"),
    _us("us_comm", "美股通訊服務", "網路平台、媒體、電信、遊戲"),
    _us("us_consumer_disc", "美股非必需消費", "電商、汽車、零售、餐飲、旅遊"),
    _us("us_staples", "美股必需消費", "食品、飲料、日用品、量販"),
    _us("us_health", "美股醫療保健", "藥廠、生技、醫材、醫療服務與健保、實驗儀器"),
    _us("us_financials", "美股金融", "銀行、券商、保險、支付"),
    _us("us_industrials", "美股工業", "航太國防、機械、運輸、工程"),
    _us("us_energy", "美股能源", "石油、天然氣"),
    _us("us_materials", "美股原物料", "化工、金屬、礦業"),
    _us("us_utilities", "美股公用事業", "電力、天然氣、水"),
    _us("us_real_estate", "美股房地產", "REITs、不動產"),
)
SECTORS: tuple[Tag, ...] = (*TW_SECTORS, *US_SECTORS)

# A headline given one of these sectors also gets the industry's theme (the hints say 「金融股的新聞都選」, but the
# model sometimes files a bank's outage only under 事故／資安 and the sector).
THEMES_OF_SECTOR: dict[str, str] = {
    "17": "finance", "us_financials": "finance",
    "15": "shipping",
    "22": "biotech", "us_health": "biotech",
    "14": "property", "us_real_estate": "property",
    "23": "oil_energy", "us_energy": "oil_energy",
    "12": "ev_auto",
    "35": "green_energy",
}

THEME_BY_ID = {t.id: t for t in THEMES}
SECTOR_BY_ID = {t.id: t for t in SECTORS}
THEME_ID_BY_LABEL = {t.label: t.id for t in THEMES}
SECTOR_ID_BY_LABEL = {t.label: t.id for t in SECTORS}
TW_SECTOR_ID_BY_LABEL = {t.label: t.id for t in TW_SECTORS}


def theme_label(theme_id: str) -> str | None:
    t = THEME_BY_ID.get(theme_id)
    return t.label if t else None


def sector_label(sector_id: str) -> str | None:
    t = SECTOR_BY_ID.get(sector_id)
    return t.label if t else None


def _key(text: str) -> str:
    return "".join(text.split()).casefold().replace("/", "／")


_THEME_LOOKUP = {**{_key(t.label): t.id for t in THEMES}, **{t.id: t.id for t in THEMES}}
_SECTOR_LOOKUP = {**{_key(t.label): t.id for t in SECTORS}, **{t.id: t.id for t in SECTORS},
                  # 「半導體」 for 半導體業 and the like: the official names end in 業 / 工業
                  **{_key(t.label.removesuffix("業")): t.id for t in TW_SECTORS if t.label.endswith("業")}}


def theme_id(text: str | None) -> str | None:
    """A theme's id from its id or label (spacing and ／ vs / ignored), else None."""
    return _THEME_LOOKUP.get(_key(text or "")) if text else None


def sector_id(text: str | None) -> str | None:
    """A sector's id from its id, label or the label without 業 (「半導體」), else None."""
    return _SECTOR_LOOKUP.get(_key(text or "")) if text else None


def tw_sector_for_industry(code: str | None = None, label: str | None = None) -> str | None:
    """The sector id of a Taiwan company from its 產業別 code (``company_profiles.industry_code``) or name."""
    if code and code in SECTOR_BY_ID and code not in _TW_SECTORS_LEFT_OUT:
        return code
    if label:
        return TW_SECTOR_ID_BY_LABEL.get(label.strip())
    return None


# SIC ranges -> US sector (first match wins; ranges are inclusive). Approximate by design (see the module docstring).
_SIC_SECTORS: tuple[tuple[int, int, str], ...] = (
    (3674, 3674, "us_semis"),
    (2830, 2836, "us_health"), (3841, 3851, "us_health"), (5122, 5122, "us_health"), (8000, 8099, "us_health"),
    (6324, 6324, "us_health"),  # hospital & medical service plans: UnitedHealth, Elevance, Cigna
    (3826, 3826, "us_health"),  # laboratory analytical instruments: Thermo Fisher, Agilent, Waters
    (2840, 2844, "us_staples"), (5400, 5499, "us_staples"), (5912, 5912, "us_staples"),
    (5331, 5331, "us_staples"), (5399, 5399, "us_staples"),  # variety / general merchandise: Walmart, Costco, Target
    (3021, 3021, "us_consumer_disc"),  # footwear: Nike, Crocs
    (4700, 4700, "us_consumer_disc"), (4724, 4724, "us_consumer_disc"),  # travel: Booking, Expedia
    (1300, 1399, "us_energy"), (2900, 2999, "us_energy"),
    (3570, 3579, "us_tech"), (3600, 3699, "us_tech"), (3820, 3829, "us_tech"), (7370, 7379, "us_tech"),
    (4800, 4899, "us_comm"), (2700, 2799, "us_comm"), (7800, 7899, "us_comm"),
    (3711, 3711, "us_consumer_disc"), (3714, 3716, "us_consumer_disc"), (3751, 3751, "us_consumer_disc"),
    (6500, 6599, "us_real_estate"), (6798, 6798, "us_real_estate"),
    (6000, 6799, "us_financials"),
    (4900, 4999, "us_utilities"),
    (1000, 1499, "us_materials"), (2400, 2699, "us_materials"), (2800, 2899, "us_materials"),
    (3000, 3099, "us_materials"), (3200, 3399, "us_materials"),
    (2000, 2199, "us_staples"),
    (2200, 2399, "us_consumer_disc"), (3100, 3199, "us_consumer_disc"), (3900, 3999, "us_consumer_disc"),
    (5200, 5999, "us_consumer_disc"), (7000, 7299, "us_consumer_disc"), (7900, 7999, "us_consumer_disc"),
    (1500, 1799, "us_industrials"), (3400, 3569, "us_industrials"), (3580, 3599, "us_industrials"),
    (3700, 3799, "us_industrials"), (3800, 3899, "us_industrials"), (4000, 4799, "us_industrials"),
    (5000, 5199, "us_industrials"), (7300, 7369, "us_industrials"), (7380, 7399, "us_industrials"),
    (8700, 8799, "us_industrials"),
)


def us_sector_for_sic(sic: str | int | None) -> str | None:
    """The US sector id of an SEC SIC code (``sec_companies.profile["sic"]``), else None."""
    try:
        n = int(str(sic).strip())
    except (TypeError, ValueError):
        return None
    return next((sector for lo, hi, sector in _SIC_SECTORS if lo <= n <= hi), None)


# Companies whose SIC code puts them in another sector than the vocabulary's (GICS-like) one: the companies the hints
# name, and the large ones where SIC and GICS disagree (interactive media and games in 7370 / 7372, payments in 7374 /
# 7389, health plans and lab tools, discount stores, travel sites, equipment makers outside 3674).
US_SECTOR_BY_TICKER: dict[str, str] = {
    **{ticker: sector for sector, examples in US_SECTOR_EXAMPLES.items() for ticker, _ in examples},
    **dict.fromkeys(("GOOG", "DJT", "SNAP", "PINS", "RDDT", "DIS", "EA", "TTWO", "RBLX", "MTCH", "WBD"), "us_comm"),
    **dict.fromkeys(("MA", "PYPL", "FI", "FIS", "GPN", "XYZ", "COIN", "AXP"), "us_financials"),
    **dict.fromkeys(("ELV", "CI", "HUM", "CNC", "MOH", "TMO", "DHR", "A", "WAT", "IQV"), "us_health"),
    **dict.fromkeys(("TGT", "DG", "DLTR"), "us_staples"),
    **dict.fromkeys(("BKNG", "EXPE", "ABNB", "DASH", "EBAY"), "us_consumer_disc"),
    **dict.fromkeys(("LRCX", "KLAC", "TER", "ASML", "TSM"), "us_semis"),
    **dict.fromkeys(("ACN", "IBM"), "us_tech"),
    **dict.fromkeys(("UBER", "LYFT", "ADP", "PAYX"), "us_industrials"),
}


def us_sector(ticker: str | None, sic: str | int | None = None) -> str | None:
    """A US company's sector id: :data:`US_SECTOR_BY_TICKER` first, else its SIC code's."""
    return US_SECTOR_BY_TICKER.get((ticker or "").upper()) or us_sector_for_sic(sic)
