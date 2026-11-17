"""Which English headlines are about a US stock or the US market (產品負責人 2026-11-17, option A: 照建議).

Why
---
GDELT's DOC API answers 429 to nearly every request from Railway's shared outbound IPs (one request per 5 s per IP,
shared with other tenants). US stocks and the US market's headlines now come from the English GKG bulk files the
worker already reads for Taiwan stocks (:mod:`forliosa.news.gdelt_bulk`): no extra download. The DOC API's
``(sourcecountry:US OR sourcecountry:UK) sourcelang:english`` becomes an allowlist of US and UK news outlets
(:data:`forliosa.news.outlets.US_NEWS_DOMAINS`, :func:`~forliosa.news.outlets.is_us_outlet`), and the DOC API's
full-text match becomes a test of the **page title** alone. Precision before recall: a story about another company (or
about the fruit) is worse than one story fewer.

When a title is about the company (:meth:`UsTerms.matches`)
------------------------------------------------------------
* **The ticker in a finance context**: ``$NVDA``, ``(NVDA)``, ``(Nasdaq: NVDA)``, ``NYSE: F``, ``NVDA stock`` /
  ``shares``. One-letter tickers only as ``$F`` or ``NYSE: F``; a ticker that is also a common abbreviation (AI, ESG,
  IPO: :data:`~forliosa.news.us_words.ABBREVIATIONS`) not as 「AI stock」 or 「(AI)」. A bare ticker is not enough
  (「META」「SNAP」「F」).
* **A distinctive name** (``strong``): Nvidia, Palantir, Google, a full name of several words that are not all everyday
  words (Palantir Technologies, Advanced Micro Devices, Coca-Cola), as a proper noun: a whole word, its first letter a
  capital (「Nvidia's」 counts, 「nvidia」 does not), not joined by a hyphen to a lower-case word or a compound tail
  (「Nvidia-backed」; 「Tesla-SpaceX」「Nvidia-Anthropic Week」 and 「ex-Nvidia」 count).
* **An everyday-word name we curated** (``everyday``: Apple, Amazon, Meta, Target, Visa, Snap, Block, Gap, Ford; the
  surname Goldman) only
  with company context in the same title: the name followed by stock / shares / earnings / CEO / Inc. / Holdings
  (「Target Stock Falls」); the company's own words (iPhone, Tim Cook; AWS, Bezos; Zuckerberg, Instagram); the ticker;
  or, in a sentence-case title — where a capital letter in mid-sentence marks a proper noun — a finance word in the
  title (shares, earnings, revenue, investors, CEO, Wall Street…) or a business page (a business or technology outlet,
  or a business section); at the very start of a sentence-case title only the finance word counts (「Target cuts
  forecast…」 yes, 「Strategy shift at…」 no). A Title Case title (most words capitalised: NYT, IBD, Engadget) gives no
  such hint, so there only the first three count (「Nvidia Stock Fills Gap」 is not about Gap).
* **Any other everyday single word** (``strict``: from SEC's name and in the measured list
  :data:`~forliosa.news.us_words.EVERYDAY_NAME_WORDS` — Outlook, Track, Here, Bill, Fold, Hub — the market's own names
  Dow and Nasdaq for Dow Inc. and Nasdaq, Inc., and the English county Berkshire): only the company context of the
  first two (「Here's why」「Bill Ackman」「Outlook outage」「Dow Jones futures」「Reading, Berkshire」 are not those
  companies).
* **A distinctive single word from SEC's name** (``plain``: 「Hasbro」「Amgen」「Navan」): a finance word, or a business
  page in a sentence-case title; not right after another capitalised word in a sentence-case title (「Serena Williams」
  is not the Williams Companies).
* Never inside a phrase that names something else: a hyphenated word for any name but a distinctive one
  (「Williams-Sonoma」 is not Sonoma), 「the … of」 (「the Ferrari of AI」), the next word of another SEC company's name
  (Apple Hospitality, Target Hospitality, Meta Critical Minerals, Coca-Cola Consolidated) or the word before the name in
  one (H&R Block), and the curated phrases of :data:`US_HINTS` (Big Apple, Apple pie, Amazon rainforest, Doug Ford,
  H-1B visa, snap election, Oracle of Omaha, price target, Uber driver; Intel as intelligence — 「Key Iran Intel」
  「Senate Intel Committee」 —, Ron or Rep. Dan Goldman, Citi Bike, Merck KGaA); for a bank or brokerage
  (:data:`BROKERAGES`), never as the source of a research call (「Morgan Stanley S&P 500 target」「Goldman says…」
  「double upgrade from Mizuho」). A longer name left out this way is not rescued by a shorter one inside it
  (「Goldman Sachs raises its Nvidia target」 is not saved by 「Goldman」).

Names come from the catalog (SEC's ``company_tickers.json`` title, built-in names and ASCII aliases), corporate
suffixes removed (「AMAZON COM INC」→ Amazon, 「Palantir Technologies Inc.」→ Palantir Technologies and its first word
Palantir when no other SEC company's name starts with it, as ``ai.analyst.us_brand``), plus :data:`US_HINTS` for the
names news use that SEC's do not (Google, Disney, JPMorgan, TSMC) and for each everyday-word name's own words.

The US market (:func:`market_matches`): the DOC query's intent — Wall Street, the S&P 500, the Dow, the Nasdaq — plus
US stock-market and Fed-rate headlines, never a press release's ``(Nasdaq: XYZ)`` or a story about another market.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.marketdata.base import InstrumentInfo
from forliosa.news.normalize import COMMON_WORDS, collapse_spaces
from forliosa.news.outlets import is_us_business_page
from forliosa.news.us_words import ABBREVIATIONS, EVERYDAY_NAME_WORDS

STRONG, EVERYDAY, STRICT, PLAIN = "strong", "everyday", "strict", "plain"

# Everyday English words, places and people's names that are also (the first word of) US company names, beyond
# normalize.COMMON_WORDS and the measured us_words.EVERYDAY_NAME_WORDS: a curated ``weak`` name of US_HINTS follows the
# everyday rules, any other listed single word the strict ones.
US_EVERYDAY_WORDS = frozenset({
    "affirm", "ally", "alphabet", "amazon", "analog", "applied", "arm", "asana", "block", "booking", "carnival",
    "caterpillar", "chewy", "chevron", "corning", "dell", "discover", "dollar", "dominion", "equity", "ford", "gap",
    "hershey", "intuitive", "iron", "lilly", "lucid", "match", "meta", "morgan", "oracle", "palo", "peloton",
    "progressive", "public", "realty", "robinhood", "rocket", "schwab", "shell", "snap", "snowflake", "square",
    "strategy", "texas", "toast", "travelers", "visa", "walt", "wells", "workday", "zoom",
})
# A word after a name that makes it the company: 「Apple Stock」「Target's CEO」「Gap Inc.」.
_COMPANY_NEXT = re.compile(r"^(?:['’]s)?\s+(?:stocks?|shares?|share price|earnings|CEO|CFO|chief executive|Inc\b\.?|"
                           r"Corp\b\.?|Corporation|Co\b\.|Holdings?|Ltd\b\.?|plc|revenue|sales|profits?|investors|"
                           r"shareholders)\b", re.IGNORECASE)
# The same for a ``strict`` name, without the words that also follow the market's names (「Dow stocks」 are the index's
# members, 「Nasdaq investors」 trade there).
_STRICT_NEXT = re.compile(r"^(?:['’]s)?\s+(?:stock|shares|share price|earnings|CEO|CFO|chief executive|Inc\b\.?|"
                          r"Corp\b\.?|Corporation|Co\b\.|Holdings?|Ltd\b\.?|plc|revenue|profits?|shareholders)\b",
                          re.IGNORECASE)
# Finance words that make a title business news (case-insensitive, whole words).
FINANCE_CUE = re.compile(
    r"(?<![A-Za-z0-9])(?:stocks?|shares|shareholders?|stockholders?|investors?|earnings|revenues?|profits?|quarterly|"
    r"Q[1-4]|guidance|sales|CEO|CFO|chief executive|Wall St(?:reet|\.)?|Nasdaq|NYSE|S&P 500|market (?:cap|value)|"
    r"valuation|IPO|dividends?|buybacks?|analysts?|downgrades?|upgrades?|layoffs|job cuts|acquisition|acquires?|"
    r"acquired|merger|takeover|antitrust|retailer|chipmaker|automaker|carmaker|tech giant|Big Tech|"
    r"breaks? out|breakout|buy zone|buy point|price target|52-week|IBD|"
    r"\$\s?\d[\d.,]*\s*(?:billion|bn|million|trillion))(?![A-Za-z0-9])",
    re.IGNORECASE)
_EXCHANGES = (r"(?:Nasdaq(?:GS|GM|CM)?|NASDAQ(?:GS|GM|CM)?|NYSE(?:\s?American|\s?Arca|Arca)?|AMEX|Amex|Cboe|CBOE|"
              r"BATS|OTC(?:QX|QB)?|OTC Markets)")
_CORPORATE_SUFFIX = re.compile(
    r"[\s,]+(?:corporation|corp|incorporated|inc|co|company|companies|ltd|limited|plc|llc|lp|l\.p|n\.v|nv|s\.a|sa|ag|"
    r"se|holdings?|group|trust|class [a-z])\.?$", re.IGNORECASE)
_SLASH_SUFFIX = re.compile(r"\s*/[A-Z]{2,3}/?\s*$|\s*/(?:NEW|DE|MD|NV|UK|OH|MN|PA|NY|CA|TX|WA)/?\s*$", re.IGNORECASE)
# The rest of a name that does not change who the company is: 「Palantir Technologies」 is Palantir.
_GENERIC_TAIL = frozenset({
    "technologies", "technology", "platforms", "systems", "communications", "global", "international", "industries",
    "software", "semiconductor", "semiconductors", "pharmaceuticals", "therapeutics", "biosciences", "entertainment",
    "brands", "markets", "financial", "labs", "solutions", "services", "enterprises", "interactive", "automotive",
    "wholesale", "motors", "networks", "com", "digital", "worldwide", "resources", "energy", "health", "healthcare",
})


@dataclass(frozen=True)
class Hint:
    """What news call a US company beyond SEC's name: ``strong`` names that are the company alone (Google, TSMC),
    ``weak`` names that are also everyday words (Apple), ``strict`` names that are mostly something else (Dow,
    Nasdaq: the market), ``cues`` — the company's own words (products, people) that make an everyday-word name the
    company — and phrases that make it something else: ``not_before`` / ``not_after`` (the word right before / after
    the name), ``not_with`` (anywhere in the title)."""

    strong: tuple[str, ...] = ()
    weak: tuple[str, ...] = ()
    strict: tuple[str, ...] = ()
    cues: tuple[str, ...] = ()
    not_before: tuple[str, ...] = ()
    not_after: tuple[str, ...] = ()
    not_with: tuple[str, ...] = ()


_VISA_NOT_BEFORE = ("H-1B", "H1B", "H-2B", "golden", "student", "work", "travel", "tourist", "investor", "e", "EB-5",
                    "O-1", "L-1", "K-1", "J-1", "F-1", "spousal", "transit", "entry", "immigrant", "skilled", "the")
_VISA_NOT_AFTER = ("rules", "rule", "fee", "fees", "applications", "application", "applicants", "holders", "holder",
                   "program", "programs", "policy", "policies", "ban", "bans", "waiver", "waivers", "requirements",
                   "restrictions", "interview", "interviews", "appointment", "appointments", "overstay", "overstays",
                   "free", "bulletin", "lottery", "processing", "status", "denial", "denials", "cap", "caps",
                   "sponsorship", "system", "regime", "scheme", "route", "routes", "changes", "crackdown", "pause")
_BERKSHIRE_CUES = ("Buffett", "Greg Abel", "Ajit Jain", "Munger", "Omaha", "GEICO", "BNSF")
# Curated: the stocks Taiwanese investors hold most (by the 2026-11 watchlists and holdings) and every everyday-word
# name the measurement of 2026-11-17 met. Keys are tickers as the catalog spells them.
US_HINTS: dict[str, Hint] = {
    "AAPL": Hint(weak=("Apple",), cues=("iPhone", "iPhones", "iPad", "Mac", "MacBook", "iOS", "macOS", "Siri",
                                        "Tim Cook", "App Store", "AirPods", "Vision Pro", "Apple Intelligence",
                                        "Apple TV", "Apple Pay", "Apple Watch", "Apple Music", "Apple Maps",
                                        "Cupertino"),
                 not_before=("Big", "candy", "caramel", "toffee", "crab", "Adam's"),
                 not_after=("pie", "pies", "cider", "orchard", "orchards", "crumble", "cake", "tart", "juice", "sauce",
                            "Daily", "Valley", "picking", "trees", "tree", "harvest", "Cup", "Hospitality"),
                 not_with=("recipe", "recipes", "orchard", "Thanksgiving dessert", "Thanksgiving desserts")),
    "MSFT": Hint(strong=("Microsoft",)),
    "NVDA": Hint(strong=("Nvidia", "NVIDIA")),
    "AMZN": Hint(weak=("Amazon",), cues=("AWS", "Amazon Web Services", "Prime", "Prime Video", "Prime Day", "Alexa",
                                         "Kindle", "Kuiper", "Zoox", "Bezos", "Jassy", "Whole Foods", "Black Friday",
                                         "Cyber Monday", "MGM", "Twitch", "e-commerce", "warehouse", "warehouses",
                                         "satellites", "affiliate"),
                 not_before=("the", "Brazilian", "Peruvian", "Colombian", "Ecuadorian", "Bolivian"),
                 not_after=("rainforest", "rainforests", "forest", "forests", "river", "basin", "jungle", "region",
                            "tribe", "tribes", "fires", "fire", "deforestation", "warriors", "women"),
                 not_with=("rainforest", "deforestation", "indigenous", "jungle", "Amazonia", "Amazon basin",
                           "Amazon River", "COP30", "COP31", "Brazil's Amazon", "Belém", "Belem")),
    "GOOGL": Hint(strong=("Google", "Alphabet")),  # not Waymo / DeepMind alone: 「…competition with Waymo」
    "GOOG": Hint(strong=("Google", "Alphabet")),
    "META": Hint(weak=("Meta",), strong=("Meta Platforms",),
                 cues=("Zuckerberg", "Facebook", "Instagram", "WhatsApp", "Threads", "Llama", "Reality Labs",
                       "Ray-Ban", "Oculus", "Quest", "smart glasses", "superintelligence"),
                 not_after=("Critical", "Materials", "analysis", "data"), not_before=("the",)),
    "TSLA": Hint(strong=("Tesla",), not_before=("Nikola",), not_after=("coil", "coils")),
    "PLTR": Hint(strong=("Palantir",)),
    "AMD": Hint(strong=("AMD", "Advanced Micro Devices")),
    "AVGO": Hint(strong=("Broadcom",)),
    "TSM": Hint(strong=("TSMC", "Taiwan Semiconductor Manufacturing", "Taiwan Semiconductor")),
    "NFLX": Hint(strong=("Netflix",)),
    # 「Intel」 is also intelligence, capitalised in Title Case: 「…Ignoring Key Iran Intel」「U.S. Intel Warns Iran
    # Plotting…」「Senate Intel Committee…」「House Intel chair…」 (newsweek, foxnews; 2026-11-17 review). A country, an
    # agency or a chamber before it, or an intelligence word after it, makes it intelligence unless the company's own
    # words are in the title (「US Intel stake」 is the government's shareholding).
    "INTC": Hint(strong=("Intel",),
                 cues=("Intel stock", "Intel shares", "Intel stake", "Intel CEO", "Intel chips", "Intel Foundry",
                       "Lip-Bu Tan", "Gelsinger", "Xeon", "Core Ultra", "18A"),
                 not_before=("iran", "iranian", "us", "u.s.", "american", "ukraine", "ukrainian", "russia", "russian",
                             "israel", "israeli", "british", "uk", "u.k.", "western", "allied", "senate", "house",
                             "congressional", "military", "pentagon", "secret", "classified", "fresh", "faulty", "raw",
                             "actionable", "sensitive", "cia", "fbi", "nsa", "defense", "defence", "battlefield"),
                 not_after=("agencies", "agency", "community", "officials", "report", "reports", "chief", "chiefs",
                            "sources", "assessment", "assessments", "sharing", "failure", "failures", "gathering",
                            "committee", "committees", "panel", "panels", "chair", "chairman", "chairwoman",
                            "briefing", "briefings", "leak", "leaks", "leaked", "dossier", "operative", "operatives",
                            "officer", "officers", "suggests", "indicates", "gap", "gaps", "lapse", "lapses"),
                 not_with=("intelligence agencies",)),
    "MU": Hint(strong=("Micron",)),
    "QCOM": Hint(strong=("Qualcomm",)),
    "ARM": Hint(weak=("Arm",), strong=("Arm Holdings",), cues=("SoftBank", "chip", "chips", "chipmaker", "Rene Haas",
                                                                "semiconductor", "licensing")),
    "ORCL": Hint(strong=("Oracle",), not_after=("of", "Park", "Arena", "Team", "Red Bull"),
                 not_before=("the", "Delphic", "an"), not_with=("Oracle of Omaha",)),
    "CRM": Hint(strong=("Salesforce",)),
    "ADBE": Hint(strong=("Adobe",)),
    "IBM": Hint(strong=("IBM",)),
    "CSCO": Hint(strong=("Cisco",)),
    "SMCI": Hint(strong=("Super Micro", "Supermicro", "Super Micro Computer")),
    "COIN": Hint(strong=("Coinbase",)),
    "MSTR": Hint(weak=("Strategy",), strong=("MicroStrategy",), cues=("Saylor", "bitcoin", "Bitcoin")),
    "UBER": Hint(strong=("Uber",), not_after=("driver",)),  # 「…attack on an Uber driver」: a crime story
    "ABNB": Hint(strong=("Airbnb",)),
    "SHOP": Hint(strong=("Shopify",)),
    "V": Hint(weak=("Visa",), cues=("Mastercard", "card network", "card networks", "swipe fees", "interchange",
                                    "payments network", "payments giant", "payment network"),
          not_before=_VISA_NOT_BEFORE, not_after=_VISA_NOT_AFTER,
          not_with=("H-1B", "H1B", "immigration", "immigrants", "migrants", "visas", "deportation", "asylum",
                    "green card", "Gold Card", "travel ban", "embassy", "consulate", "State Department")),
    "MA": Hint(strong=("Mastercard",)),
    "PYPL": Hint(strong=("PayPal",)),
    "XYZ": Hint(weak=("Block",), strong=("Cash App", "Afterpay"), cues=("Dorsey", "Square", "bitcoin", "Bitcoin"),
                not_before=("the", "city", "voting", "trade", "Soviet", "Eastern", "a", "building", "apartment",
                            "H&R"),  # H&R Block, the tax firm (also by SEC's name, see us_terms)
                not_after=("Island", "party", "grant", "grants", "vote", "votes", "letters", "chain")),
    "JPM": Hint(strong=("JPMorgan", "JPMorgan Chase", "JP Morgan", "J.P. Morgan"), cues=("Dimon",)),
    "BAC": Hint(strong=("Bank of America", "BofA")),
    "WFC": Hint(strong=("Wells Fargo",)),
    # 「Goldman」 alone is also a surname (「Ron Goldman's father…」「Rep. Dan Goldman…」, 2026-11-17 review): an
    # everyday-word name, never right after a first name or a title.
    "GS": Hint(strong=("Goldman Sachs",), weak=("Goldman",), cues=("David Solomon",),
               not_before=("ron", "fred", "dan", "daniel", "emma", "william", "bill", "jason", "bruce", "kim", "nicole",
                           "lisa", "rep", "rep.", "sen", "sen.", "mr", "mr.", "ms", "ms.", "mrs", "mrs.", "dr", "dr.",
                           "judge", "rabbi")),
    "MS": Hint(strong=("Morgan Stanley",)),
    "C": Hint(strong=("Citigroup", "Citi"), not_after=("bike", "bikes", "field")),  # NYC's bike share, the Mets' park
    # 「Berkshire」 alone is also an English county (「Reading, Berkshire: house prices…」「Berkshire council…」,
    # 2026-11-17 review): only with the company's own words or 「Berkshire shares」-like context, as the market's names.
    "BRK-B": Hint(strong=("Berkshire Hathaway",), strict=("Berkshire",), cues=_BERKSHIRE_CUES),
    "BRK-A": Hint(strong=("Berkshire Hathaway",), strict=("Berkshire",), cues=_BERKSHIRE_CUES),
    "KO": Hint(strong=("Coca-Cola", "Coca Cola", "Coke")),
    "PEP": Hint(strong=("PepsiCo", "Pepsi")),
    "MCD": Hint(strong=("McDonald's", "McDonalds")),
    "SBUX": Hint(strong=("Starbucks",)),
    "NKE": Hint(strong=("Nike",)),
    "DIS": Hint(strong=("Disney", "Walt Disney")),
    "WMT": Hint(strong=("Walmart",)),
    "COST": Hint(strong=("Costco",)),
    "TGT": Hint(weak=("Target",), cues=("retailer", "Fiddelke", "Brian Cornell", "Black Friday", "big-box"),
                not_before=("price", "Price", "on", "off", "a", "the", "easy", "prime", "top", "key", "inflation",
                            "military", "primary", "soft", "hard", "new", "potential", "next", "main", "biggest"),
                not_after=("price", "prices", "practice", "date", "rate", "rates", "audience", "list", "of",
                           "Hospitality", "Group", "range", "zone", "market", "hit", "areas", "area")),
    "HD": Hint(strong=("Home Depot",)),
    "GAP": Hint(weak=("Gap",), strong=("Gap Inc", "Old Navy", "Banana Republic", "Athleta"),
                cues=("retailer", "Richard Dickson", "apparel"),
                not_before=("the", "a", "pay", "wage", "wealth", "gender", "funding", "budget", "trade", "skills",
                            "price", "valuation", "credibility", "racial", "income", "growing", "widening", "narrow",
                            "narrowing", "huge", "big"),
                not_after=("year", "years", "between", "up", "down", "fill", "fills", "in", "of", "widens",
                           "narrows", "closes")),
    "F": Hint(weak=("Ford",), strong=("Ford Motor", "Ford Motor Company"),
              cues=("F-150", "Mustang", "Bronco", "Farley", "automaker", "carmaker", "Lincoln", "EV", "EVs",
                    "recall", "recalls", "pickup", "pickups", "UAW", "dealers", "Ford Pro"),
              not_before=("Doug", "Harrison", "Gerald", "Tom", "Rob", "Betty", "Henry", "John", "Michael", "Colin",
                          "Jack", "Whitey", "Christine", "Blasey", "Premier", "President", "Mr", "Mr.", "Ms",
                          "Ms.", "Dr", "Dr."),
              not_after=("Foundation", "Field", "Center", "Theatre", "Theater", "Island", "government",
                         "administration")),
    "GM": Hint(strong=("General Motors",), cues=("Barra",)),
    "BA": Hint(strong=("Boeing",)),
    "LLY": Hint(strong=("Eli Lilly",), weak=("Lilly",), cues=("Zepbound", "Mounjaro", "orforglipron", "obesity",
                                                              "weight-loss", "GLP-1")),
    "NVO": Hint(strong=("Novo Nordisk",), cues=("Wegovy", "Ozempic")),
    "PFE": Hint(strong=("Pfizer",)),
    "MRK": Hint(strong=("Merck",), not_after=("KGaA", "Serono")),  # the German Merck (Darmstadt), not MRK
    "JNJ": Hint(strong=("Johnson & Johnson", "J&J")),
    "UNH": Hint(strong=("UnitedHealth", "UnitedHealthcare")),
    "XOM": Hint(strong=("Exxon", "ExxonMobil", "Exxon Mobil")),
    "CVX": Hint(strong=("Chevron",), not_after=("deference", "doctrine", "ruling", "decision", "precedent")),
    "T": Hint(strong=("AT&T",)),
    "VZ": Hint(strong=("Verizon",)),
    "SNAP": Hint(weak=("Snap",), strong=("Snapchat",), cues=("Evan Spiegel", "Spiegel"),
                 not_after=("election", "elections", "poll", "polls", "vote", "decision", "judgment", "judgement",
                            "shot", "shots", "freeze", "back", "benefits", "recipients", "cuts", "funding", "food",
                            "program", "payments", "on", "up"),
                 not_with=("food stamps", "SNAP benefits", "election")),
    "BABA": Hint(strong=("Alibaba",)),
    "ASML": Hint(strong=("ASML",)),
    "SPOT": Hint(strong=("Spotify",)),
    "RIVN": Hint(strong=("Rivian",)),
    "LCID": Hint(weak=("Lucid",), strong=("Lucid Motors", "Lucid Group"), cues=("EV", "EVs", "Gravity", "Air sedan")),
    "SOFI": Hint(strong=("SoFi",)),
    "HOOD": Hint(strong=("Robinhood",), not_before=("Robin",)),
    "DELL": Hint(strong=("Dell Technologies",), weak=("Dell",), cues=("Michael Dell", "servers", "PC", "PCs")),
    "HPQ": Hint(strong=("HP Inc",), cues=("printers", "PC", "PCs")),
    "ASAN": Hint(weak=("Asana",), cues=("Moskovitz", "work management")),
    "CRWV": Hint(strong=("CoreWeave",)),
    "OKLO": Hint(strong=("Oklo",)),
    "AMAT": Hint(strong=("Applied Materials",)),
    "LRCX": Hint(strong=("Lam Research",)),
    "PANW": Hint(strong=("Palo Alto Networks",)),
    "CRWD": Hint(strong=("CrowdStrike",)),
    "NOW": Hint(strong=("ServiceNow",)),
    "SNOW": Hint(weak=("Snowflake",), cues=("data cloud", "AI Data Cloud")),
    "DDOG": Hint(strong=("Datadog",)),
    "LULU": Hint(strong=("Lululemon",)),
    # the market's own names (measured 2026-11-17: 「Dow Jones Futures: …」「…Cast Pall On Nasdaq」)
    "DOW": Hint(strict=("Dow",), strong=("Dow Chemical",), cues=("Jim Fitterling", "Fitterling")),
    "NDAQ": Hint(strict=("Nasdaq",), cues=("Adena Friedman", "exchange operator")),
    "DIA": Hint(not_after=("top", "newswires")),  # Dow Jones Newswires' 「Dow Jones Top Company Headlines at 7 PM ET」
}


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[\s\-]+", name.strip()) if w]


def strip_corporate(name: str) -> str:
    """SEC's or the catalog's name without suffixes: 「AMAZON COM INC」→「AMAZON」, 「Asana, Inc.」→「Asana」,
    「JPMORGAN CHASE & CO」→「JPMORGAN CHASE」, 「COSTCO WHOLESALE CORP /NEW」→「COSTCO WHOLESALE」."""
    t = collapse_spaces(name or "")
    for _ in range(4):
        before = t
        t = _SLASH_SUFFIX.sub("", t)
        t = _CORPORATE_SUFFIX.sub("", t).strip(" ,&")
        t = re.sub(r"\s+(?:&|and)$", "", t, flags=re.IGNORECASE)
        if t.upper().endswith(" COM"):
            t = t[:-4]
        if t == before:
            break
    return t.strip()


def _is_everyday(word: str) -> bool:
    w = word.casefold().strip("'’.")
    return w in COMMON_WORDS or w in US_EVERYDAY_WORDS or w in EVERYDAY_NAME_WORDS or w.upper() in ABBREVIATIONS


@functools.lru_cache(maxsize=2048)
def name_pattern(name: str, exact_acronyms: bool = True) -> re.Pattern[str]:
    """A name as a proper noun: whole words, each word's first letter as written (a capital), the rest in any case
    (「Nvidia」「NVIDIA」 for NVIDIA); a word of at most five capitals (AMD, TSMC, AWS) only in capitals; spaces and
    hyphens between words interchangeable (「Coca-Cola」「Coca Cola」); not part of a longer word. A hyphen is checked
    by :func:`_compound` (「Snap-on」 and 「Nvidia-backed」 are not the name, 「Tesla-SpaceX」 and 「ex-Nvidia」
    are)."""
    parts = []
    for w in _words(name):
        if exact_acronyms and w.isupper() and len(w) <= 5:
            parts.append(re.escape(w))
        elif w[0].isalpha():
            parts.append(re.escape(w[0]) + (f"(?i:{re.escape(w[1:])})" if len(w) > 1 else ""))
        else:
            parts.append(f"(?i:{re.escape(w)})")
    body = r"[\s\-]+".join(parts)
    return re.compile(r"(?<![A-Za-z0-9&])" + body + r"(?![A-Za-z0-9&])")


_HYPHEN_PREFIXES = frozenset({"ex", "former", "pro", "anti", "non", "post", "pre"})
_COMPOUND_TAILS = re.compile(r"(?i:backed|owned|made|rivaling|rivalling|linked|led|based|like|style|sized|related|"
                             r"focused|powered|funded|built|branded|designed|inspired|style|free|proof|friendly|"
                             r"exposed|heavy|centric|on)(?![A-Za-z])")


def _compound(title: str, m: re.Match[str], any_join: bool = False) -> bool:
    """The name is part of a hyphenated word that is not about it: joined to a lower-case word or a compound tail
    (「Snap-on」「Nvidia-backed」「Merck-Rivaling」「self-Block」), or with ``any_join`` (a name that is not
    distinctive) to anything (「Williams-Sonoma」 is not Sonoma). A distinctive name joined to another name
    (「Tesla-SpaceX merger」「Boeing-Lockheed rocket」「Nvidia-Anthropic Week」) or after 「ex-」 is still the
    company."""
    end, start = m.end(), m.start()
    if title[end:end + 1] == "-" and (any_join or title[end + 1:end + 2].islower()
                                      or _COMPOUND_TAILS.match(title, end + 1)):
        return True
    if start > 0 and title[start - 1] == "-":
        prev = re.search(r"([A-Za-z0-9]+)-$", title[:start])
        word = prev.group(1) if prev else ""
        return bool(word) and (any_join or word[0].islower()) and word.casefold() not in _HYPHEN_PREFIXES
    return False


@functools.lru_cache(maxsize=2048)
def ticker_pattern(ticker: str) -> re.Pattern[str] | None:
    """The ticker in a finance context (see the module docstring); ``BRK-B`` also as ``BRK.B`` / ``BRK/B``."""
    t = (ticker or "").strip().upper()
    if not t or not re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.\-/][A-Z0-9]+)?", t):
        return None
    tk = re.sub(r"\\?[.\-/]", r"[.\\-/]", re.escape(t))
    end = r"(?![A-Za-z0-9])"
    forms = [rf"\${tk}{end}(?!-)", rf"{_EXCHANGES}\s*:\s*{tk}{end}", rf"\(\s*{_EXCHANGES}\s*:\s*{tk}\s*\)"]
    if len(t) >= 2 and t not in ABBREVIATIONS:  # 「AI stocks」「artificial intelligence (AI)」 are not C3.ai
        forms += [rf"\(\s*{tk}\s*\)", rf"(?<![A-Za-z0-9$])\b{tk}\s+(?i:stock|stocks|shares|share price|options)\b"]
    return re.compile("|".join(forms))


# Words Title Case styles keep in lower case (articles, conjunctions, prepositions): not counted by _title_case.
_SMALL_WORDS = frozenset({
    "and", "the", "for", "but", "nor", "yet", "with", "from", "into", "over", "onto", "upon", "than", "that", "via",
    "per", "off", "out", "about", "after", "under", "between", "through", "without", "against", "during", "before",
    "since", "until", "among", "across", "behind", "beyond", "near", "like", "toward", "towards", "within", "amid",
})


def _title_case(title: str) -> bool:
    """Title Case (or capitals): no word of three letters or more after the first is in lower case, small words aside
    (「Nvidia Stock Fills Gap」, NYT's 「Trump Says He's Open to Reinstatement of Jensen Huang as Nvidia Chief」). A
    capital letter then says nothing about a proper noun. A sentence-case title full of names (「Robert Pattinson is
    Amazon's first James Bond」) still has a lower-case word."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’]*", title)[1:] if len(w) >= 3 and w.casefold() not in
             _SMALL_WORDS]
    return len(words) >= 2 and not any(w[0].islower() for w in words)


# After an everyday-word name at the start of a sentence-case title on a business page: a word that makes it the
# subject of a company story (「Apple has already renewed…」「Target to close…」「Apple's AI chief…」), not a common
# phrase (「Strategy shift…」「Gap between…」「Block grants…」).
_SUBJECT_NEXT = re.compile(
    r"^(?:['’]s\s|\s+(?:is|was|has|had|have|could|would|will|can|may|might|should|must|says|said|to|plans|adds|"
    r"launches|unveils|reveals|announces|reports|posts|cuts|raises|sues|sued|wins|loses|buys|sells|hires|fires|opens|"
    r"closes|beats|misses|warns|faces|expands|delays|recalls|agrees|settles|names|taps|drops|ends|pulls|pauses|"
    r"halts|stops|tests|rolls|brings|makes|takes|gets|wants|needs|says|confirms|denies|invests|acquires|partners|"
    r"teams|signs|files|seeks|bets|pushes|hits|slashes|boosts|lowers|lifts)\b)")


def _word_before(title: str, start: int) -> str:
    m = re.search(r"([A-Za-z0-9&.'’\-]+)[\s\"“”'‘]*$", title[:start])
    return m.group(1).casefold().strip("'’") if m else ""


def _word_after(title: str, end: int) -> str:
    m = re.match(r"(?:['’]s)?[\s\"“”'‘]*([A-Za-z0-9&\-]+)", title[end:])
    return m.group(1).casefold() if m else ""


# Banks and brokerages whose research is in the news far more than the firm itself (「Morgan Stanley S&P 500 target」
# 「Goldman says…」「double upgrade from Mizuho」, measured 2026-11-17; ``ai.analyst._NOT_A_BRAND`` keeps the same firms
# out of the analyst card's brand names). By name (case-folded), so every listing of the firm counts: MS-PK, Mizuho's
# MFG and MZHOF.
BROKERAGES = frozenset({
    "goldman", "goldman sachs", "morgan stanley", "jpmorgan", "jpmorgan chase", "jp morgan", "j.p. morgan",
    "bank of america", "bofa", "citi", "citigroup", "wells fargo", "jefferies", "jefferies financial", "mizuho",
    "mizuho financial", "raymond james", "raymond james financial", "piper sandler", "stifel", "stifel financial",
    "nomura", "truist", "truist financial", "hsbc", "barclays", "deutsche bank", "ubs", "evercore", "keycorp",
    "keybanc", "rbc", "royal bank of canada", "td", "toronto-dominion bank", "bmo", "bank of montreal", "cibc",
    "scotiabank", "bank of nova scotia", "lazard", "bernstein", "oppenheimer", "wedbush", "needham", "cantor",
    "baird", "macquarie", "bnp paribas", "societe generale", "credit agricole",
})
_RESEARCH_BEFORE = re.compile(r"(?i:\b(?:from|per|according to)\s*)$")
_RESEARCH_AFTER = re.compile(
    r"^(?:['’]s)?\s+(?i:(?:chief\s+)?(?:strategists?|analysts?|economists?|research|equity research)\b|"
    r"(?:says|said|sees|expects|predicts|forecasts?|warns|upgrades?|downgrades?|initiates|reiterates|rates|"
    r"bullish|bearish)\b|(?:\S+\s+){0,3}(?:price\s+)?targets?\b|"
    r"(?:raises|lifts|boosts|cuts|lowers|trims)\s+(?:\S+\s+){0,3}(?:targets?|forecasts?|ratings?|outlook|estimates?|"
    r"views?|calls?)\b)")


def _research(title: str, m: re.Match[str]) -> bool:
    """A brokerage's name as the source of a research call, not the firm as the news: 「Morgan Stanley S&P 500
    target」「Goldman says…」「Mizuho raises Nvidia target」「upgrade from Mizuho」."""
    return bool(_RESEARCH_BEFORE.search(title[:m.start()].rstrip()) or _RESEARCH_AFTER.match(title[m.end():]))


def _proper_before(title: str, start: int) -> bool:
    """Right before the name (spaces only between them) a capitalised word with lower-case letters: in a sentence-case
    title the name is part of a longer proper noun (「Serena Williams」「Toymaker Hasbro」), not an acronym (「US」)."""
    m = re.search(r"([A-Za-z][A-Za-z'’.&]*)[ \t]+$", title[:start])
    return bool(m) and m.group(1)[0].isupper() and any(c.islower() for c in m.group(1))


def _phrase_pattern(phrases: Iterable[str]) -> re.Pattern[str] | None:
    alts = sorted({p for p in phrases if p}, key=len, reverse=True)
    if not alts:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(p) for p in alts) + r")(?![A-Za-z0-9])",
                      re.IGNORECASE)


@dataclass(frozen=True)
class UsName:
    text: str
    kind: str  # strong | everyday | strict | plain
    not_after: frozenset[str] = frozenset()  # next words that make it another company (Apple Hospitality)
    not_before: frozenset[str] = frozenset()  # previous words that make it another company (H&R Block)


@dataclass(frozen=True)
class UsTerms:
    """How a US stock is named in English headlines (built by :func:`us_terms`)."""

    symbol: str
    ticker: str
    names: tuple[UsName, ...]
    cues: tuple[str, ...] = ()
    not_before: frozenset[str] = frozenset()
    not_after: frozenset[str] = frozenset()
    not_with: tuple[str, ...] = ()
    _cue_re: re.Pattern[str] | None = field(default=None, compare=False, repr=False)
    _not_with_re: re.Pattern[str] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_cue_re", _phrase_pattern(self.cues))
        object.__setattr__(self, "_not_with_re", _phrase_pattern(self.not_with))

    def _excluded(self, title: str, m: re.Match[str], name: UsName, cue: bool) -> bool:
        """Another company's name or a metaphor (「the Ferrari of AI」「the Uber of…」) always; a curated phrase that
        makes it something else unless the company's own words are in the title too (「Zuckerberg says the Meta AI
        app…」)."""
        before, after = _word_before(title, m.start()), _word_after(title, m.end())
        if after in name.not_after or before in name.not_before or (before == "the" and after == "of"):
            return True
        if name.text.casefold() in BROKERAGES and not cue and _research(title, m):
            return True
        return not cue and (before in self.not_before or after in self.not_after)

    def matches(self, title: str, url: str = "") -> bool:
        """``title`` (cleaned) names this company; ``url`` tells a business page (see the module docstring)."""
        tp = ticker_pattern(self.ticker)
        ticker = bool(tp and tp.search(title))
        if ticker:
            return True
        cue = bool(self._cue_re and self._cue_re.search(title))
        if self._not_with_re is not None and self._not_with_re.search(title) and not cue:
            return False
        titled = _title_case(title)
        finance = bool(FINANCE_CUE.search(title))
        business = is_us_business_page(url) if url else False
        excluded: list[tuple[int, int]] = []  # a longer name left out is not rescued by a shorter one inside it
        for name in sorted(self.names, key=lambda n: -len(n.text)):  # 「Goldman Sachs raises its target」, 「Goldman」
            for m in name_pattern(name.text).finditer(title):
                if any(a <= m.start() and m.end() <= b for a, b in excluded):
                    continue
                if _compound(title, m, name.kind != STRONG) or self._excluded(title, m, name, cue):
                    excluded.append((m.start(), m.end()))
                    continue
                if name.kind == STRONG:
                    return True
                rest = title[m.end():]
                if name.kind == STRICT:
                    if cue or _STRICT_NEXT.match(rest):
                        return True
                    continue
                if cue or _COMPANY_NEXT.match(rest):
                    return True
                if name.kind == PLAIN:
                    if titled and finance:
                        return True
                    if not titled and (finance or business) and not _proper_before(title, m.start()):
                        return True
                elif not titled:  # an everyday name in a sentence-case title
                    at_start = not re.search(r"[A-Za-z0-9]", title[:m.start()])
                    if finance or (business and (not at_start or _SUBJECT_NEXT.match(rest))):
                        return True
        return False


def _name_words(title: str) -> list[str]:
    return _words(strip_corporate(title or "").casefold().replace(",", " ").replace(".", " "))


def _other_companies_next_words(db: Session | None, name: str, own_cik: int | None) -> frozenset[str]:
    """The next word of every other SEC company whose name starts with ``name`` (「Apple」→ hospitality), except the
    company's own next word (「Goldman」 is followed by 「Sachs」 in Goldman Sachs BDC too)."""
    if db is None or not name:
        return frozenset()
    from forliosa.models import SecTicker

    key = _words(name.casefold().replace(",", " ").replace(".", " "))
    n = len(key)
    rows = db.execute(select(SecTicker.cik, SecTicker.title).where(func.lower(SecTicker.title).like(key[0] + "%")))
    out: set[str] = set()
    own: set[str] = set()
    for cik, title in rows:
        words = _name_words(title)
        if words[:n] != key or len(words) <= n:
            continue
        (own if own_cik is not None and cik == own_cik else out).add(words[n])
    return frozenset(out - own)


# Words before a name in another company's name that do not make it that company (「Bank of…」「The…」).
_PREV_FUNCTION_WORDS = frozenset({"the", "a", "an", "of", "and", "&", "for", "de", "du", "la", "le", "y", "in", "on",
                                  "at", "to", "by"})


def _other_companies_prev_words(db: Session | None, name: str, own_cik: int | None) -> frozenset[str]:
    """The word before ``name`` in every other SEC company's name that holds it after its first word (「Block」→
    h&r, for H&R Block), except the company's own (「Lilly」 after 「Eli」) and function words."""
    if db is None or not name:
        return frozenset()
    from forliosa.models import SecTicker

    key = _words(name.casefold())
    n = len(key)
    rows = db.execute(select(SecTicker.cik, SecTicker.title).where(func.lower(SecTicker.title).like(f"% {key[0]}%")))
    out: set[str] = set()
    own: set[str] = set()
    for cik, title in rows:
        words = _words(strip_corporate(title or "").casefold().replace(",", " "))
        for i in range(1, len(words) - n + 1):
            if words[i:i + n] == key and words[i - 1] not in _PREV_FUNCTION_WORDS:
                (own if own_cik is not None and cik == own_cik else out).add(words[i - 1].strip("'’"))
    return frozenset(out - own)


def _sec(db: Session | None, ticker: str) -> tuple[int | None, str]:
    if db is None:
        return None, ""
    from forliosa.models import SecTicker

    row = db.get(SecTicker, ticker.upper())
    return (row.cik, row.title or "") if row is not None else (None, "")


def _unique_first_word(db: Session | None, word: str) -> bool:
    """No other SEC company's name starts with ``word`` (``ai.analyst.us_brand``'s rule; without the SEC list, yes)."""
    if db is None:
        return True
    from forliosa.models import SecTicker

    rows = db.execute(select(SecTicker.cik, SecTicker.title).where(func.lower(SecTicker.title).like(f"{word}%")))
    ciks = {cik for cik, title in rows if (_words((title or "").casefold().replace(",", " ")) or [""])[0] == word}
    return len(ciks) <= 1


def _kind(name: str, hint: Hint) -> str:
    folded = name.casefold()
    if folded in {s.casefold() for s in hint.strong}:
        return STRONG
    if folded in {w.casefold() for w in hint.weak}:
        return EVERYDAY
    if folded in {w.casefold() for w in hint.strict}:
        return STRICT
    words = _words(name)
    if len(words) > 1:
        return EVERYDAY if all(_is_everyday(w) for w in words) else STRONG
    return STRICT if _is_everyday(name) else PLAIN


def us_terms(db: Session | None, info: InstrumentInfo) -> UsTerms:
    """The names, cues and exclusions of a US stock or ETF (see the module docstring). ``db`` gives SEC's company list
    (uniqueness of a first word, other companies' names); without it only the catalog and :data:`US_HINTS` are used."""
    hint = US_HINTS.get(info.code.upper(), Hint())
    cik, sec_title = _sec(db, info.code)
    candidates: list[str] = [*hint.strong, *hint.weak, *hint.strict]
    for raw in (info.name, sec_title, *(a for a in info.aliases if a.isascii())):
        full = strip_corporate(raw)
        if full.isupper():  # SEC's capitals (「GAP INC」) are not acronyms: matched as 「Gap」
            full = " ".join(w[:1] + w[1:].lower() for w in full.split())
        if len(full) < 3 or not re.search(r"[A-Za-z]", full):
            continue
        candidates.append(full)
        words = _words(full)
        if len(words) > 1 and info.type != "etf":
            first = words[0]
            rest_generic = all(w.casefold() in _GENERIC_TAIL for w in words[1:])
            if rest_generic and len(first) >= 4 and first.isalpha() and _unique_first_word(db, first.casefold()):
                candidates.append(first)
    names: list[UsName] = []
    seen: set[str] = set()
    for c in candidates:
        c = collapse_spaces(c)
        key = c.casefold()
        if key in seen or len(c) < 2 or (len(c) < 3 and c not in hint.strong):
            continue
        seen.add(key)
        kind = _kind(c, hint)
        names.append(UsName(c, kind, _other_companies_next_words(db, c, cik), _other_companies_prev_words(db, c, cik)))
    return UsTerms(symbol=info.symbol, ticker=info.code, names=tuple(names), cues=hint.cues,
                   not_before=frozenset(w.casefold() for w in hint.not_before),
                   not_after=frozenset(w.casefold() for w in hint.not_after), not_with=hint.not_with)


# -- the US market ---------------------------------------------------------------------------------------------------
_MARKET = re.compile(
    r"(?<![A-Za-z0-9])(?:Wall\s+St(?:reet|\.)?(?!\s+Journal)|S&P\s*500|S&P(?=\s+(?:futures|index|record))|"
    r"Dow\s+Jones(?!\s+Newswires)|the\s+Dow|Dow(?=\s+(?:futures|falls|rises|drops|gains|climbs|slides|jumps|sinks|"
    r"tumbles|surges|closes|ends|slips|rallies|sheds|adds|record|industrials|average|points|\d))|Nasdaq(?!\s*:|-listed|"
    r"\s+(?:listing|debut|Stockholm|Copenhagen|Helsinki|Nordic|Baltic|Dubai|Iceland|Riga|Tallinn|Vilnius|Inc|Private))|"
    r"Russell\s+2000|(?i:stock\s+market|(?:US|U\.S\.|American)\s+(?:stocks|equities|stock\s+futures)|stock\s+futures))"
    r"(?![A-Za-z0-9])")
# 「Stocks」 alone is market news when they move (「A Struggling AI Trade Is Dragging Stocks Lower」「Stocks falter
# ahead of Nvidia earnings」), not in a stock-picking list (「5 Stocks to Buy」「these 2 stocks」).
_STOCKS = re.compile(r"(?<![A-Za-z0-9])(?i:stocks)(?![A-Za-z0-9])")
_STOCKS_MOVE = re.compile(
    r"(?<![A-Za-z0-9])(?i:lower|higher|fall|falls|fell|rise|rises|rose|slide|slides|slid|slip|slips|slipped|tumble|"
    r"tumbles|tumbled|sink|sinks|sank|drop|drops|dropped|rally|rallies|rallied|gain|gains|gained|climb|climbs|"
    r"climbed|surge|surges|surged|jump|jumps|jumped|falter|falters|faltered|retreat|retreats|rebound|rebounds|"
    r"mixed|sell-off|selloff|record high|record highs|close|closes|closed|open|opens|opened|end|ends|ended)"
    r"(?![A-Za-z0-9])")
_STOCK_PICKS = re.compile(r"(?i:\b\d+\s+(?:\w+\s+){0,3}stocks\b|\b(?:these|those|top|best|worst)\s+(?:\w+\s+)?stocks\b|"
                          r"\bstocks\s+to\s+(?:buy|sell|watch|own|avoid|hold))")
_LISTING = re.compile(r"\(\s*(?:Nasdaq|NASDAQ|NYSE)[A-Za-z ]*:|listed on (?:the )?Nasdaq|(?:Nasdaq|NYSE)-listed",
                      re.IGNORECASE)
# Not the market: 「The Wolf of Wall Street」 (the film), 「Occupy Wall Street」, Dow Jones Newswires' digests
# (「Dow Jones Top Company Headlines at 7 PM ET: …」, measured 2026-11-17; its 「Top Markets Headlines」 count by what
# they say), IBD's 「Dow Jones Biotech Giant Amgen…」 (a member of the Dow, not the Dow).
_NOT_MARKET = re.compile(r"(?i:wolf of wall street|occupy wall street|wall street journal|"
                         r"dow jones (?:top [a-z]+ headlines|newswires|(?:[a-z]+ ){0,2}giants?))")
_FED = re.compile(r"(?<![A-Za-z0-9])(?:Federal Reserve|Fed|FOMC)(?:['’]s)?(?![A-Za-z0-9])")
_FED_RATES = re.compile(r"(?<![A-Za-z0-9])(?:rates?|rate[- ]cuts?|rate[- ]hikes?|cuts?|hikes?|minutes|meeting|"
                        r"decision|chair|chairman|chairwoman|policy|inflation|easing|tightening|Powell|Warsh|Hassett|"
                        r"Waller|dot plot|balance sheet)(?![A-Za-z0-9])", re.IGNORECASE)
# Other markets: a title about them is not US market news unless it also names a US index.
_OTHER_MARKET = re.compile(r"(?<![A-Za-z0-9])(?:FTSE|Nikkei|Hang Seng|Sensex|Nifty|ASX|DAX|CAC|Stoxx|STOXX|Kospi|KOSPI|"
                           r"TSX|Shanghai|Shenzhen|CSI 300|Taiex|TAIEX|Bovespa|Euro Stoxx|Asian stocks|European stocks|"
                           r"Asian markets|European markets|London stocks|Chinese stocks|Japanese stocks|Indian stocks|"
                           r"ECB|Bank of England|Bank of Japan|BOJ|RBA|RBI|Bank of Canada|SNB)(?![A-Za-z0-9])")
_US_INDEX = re.compile(r"(?<![A-Za-z0-9])(?:Wall\s+St(?:reet|\.)?|S&P\s*500|Dow\s+Jones|the\s+Dow|Nasdaq|"
                       r"Russell\s+2000|(?:US|U\.S\.)\s+stocks)(?![A-Za-z0-9])")


def market_matches(title: str, url: str = "") -> bool:
    """A US market headline: Wall Street, the S&P 500, the Dow, the Nasdaq, the Russell 2000, the stock market, US
    stocks or stock futures, stocks that move (not a list of stock picks), or the Fed with a rate word (「Fed holds
    rates」「Fed minutes」「Fed Chairman…」); not a press release's 「(Nasdaq: XYZ)」 or a listing, not 「The Wall
    Street Journal」 or 「The Wolf of Wall Street」, not another country's market (FTSE, Nikkei, the ECB…) unless a US
    index is named too. ``url`` is not used (the outlet was checked before)."""
    if _LISTING.search(title):
        return False
    text = _NOT_MARKET.sub(" ", title)
    hit = bool(_MARKET.search(text)) or bool(_FED.search(text) and _FED_RATES.search(text)) or bool(
        _STOCKS.search(text) and _STOCKS_MOVE.search(text) and not _STOCK_PICKS.search(text))
    if not hit:
        return False
    return not _OTHER_MARKET.search(text) or bool(_US_INDEX.search(text))
