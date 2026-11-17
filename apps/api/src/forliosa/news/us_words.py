"""Everyday English words that are also the first word (or the whole) of a US company's name in SEC's list.

:mod:`forliosa.news.us_match` matches a US company's single-word name (「Outlook」「Track」「Here」「Bill」) only with
company context when the word is an everyday word: a headline's 「Outlook outage」「Here's why」「Bill Ackman」 is not
about Outlook Therapeutics, Track Group, HERE or BILL Holdings. ``normalize.COMMON_WORDS`` and
``us_match.US_EVERYDAY_WORDS`` hold the curated words; this list is measured.

Measured 2026-11-17 on 48 English GKG files (12 h, 27,091 sentence-case headlines; ``CONTRACT_NOTES.md``): the first
words of SEC's company names (``sec_tickers.title`` without suffixes, ``us_match.strip_corporate``) that those headlines
write in lower case after their first word (at least three times, or once for a word of five letters or more) and at
least a quarter as often as with a capital, less a few people's and brands' names that slipped in (andersen, kirby,
lululemon, magna, stark). Words outside the list are not checked again at run time: a new company with an everyday
name is matched as a distinctive single word (a finance word or a business page) until the list is measured again.
"""

from __future__ import annotations

_MEASURED = """
above access achieve acres activate adaptive ads advance advanced advantage advent aesthetic agree align alliance
alternative amber ambitions americas angel angle apartment arch array arrive arrived artificial arts assembly
associated assured authentic auto automatic avalanche aware awareness axe baker balance ball bank banner bar barrel
bell benchmark bending beta better beyond bill bit bitcoin blend bloom bone boost boot box boxer bread brilliant
buckle build builders bullish bunker burning business butterfly cable cactus calm camping can canal cannabis canopy
caring carriage carrier cell century chain champions change charging charming charter chase check cheer chemical
cherry chime choice church circle citizens clean climb clinch cluster coastal coffee cognition collective comfort
commercial community compass complete comprehensive concrete connect consensus conservative construction consumer
consumers contemporary copper crane creative credit crisp critical cross crypto custom customers cyber decent decoy
deep definitive del design designer destination digital diploma direct disciplined disco discount distribution
district dragonfly drilling driven drugs dynamic earth eat educational electric electricity electronic elevation
else embassy emerging eminent employers enhanced enterprise entertainment entrepreneur envoy equitable essential
establishment euro everything evolution exodus expand extra extreme family farmers farmland fate federal fifth
figure finance financial firefly fitness five flag flash flexible floor flowers flutter fly fold football forge
formula fortress forum fossil foster founder four freedom freight frequency frontier frontline fuel full fury game
games gaming garden gas gates gen generate generation genuine glass glow good gorilla grab graphic gravity gray
greenway grid grocery grown hacker hammer hang happen happy harmony health healthcare healthier healthy here
heritage highway hilltop hinge hippo hold holistic honest hoops host hot hour house hub hunt hyperscale idea
immersion imperial income independence independent indie industrial information innovation innovative inspire
inspired installed instinct integrated intelligent interactive interface international invest investors invitation
jackpot jazz joint journey keen knife knowledge ladder landmark lands lantern launch launchpad laureate lead legacy
leopard liberty lifetime limitless linear linkage liquidity lithium loan local long longevity lord lower macro made
magnitude magnolia maiden main man marathon marine marker market mass medical mega mentor merchants metals mid
midcap milestone military mills mind minerals mission mixed mobility mogul monarch monster motorsport mount mountain
moving multi music natural neighborhood neo network next nice nine non noodles northeast northwest office oil old
once onto opera option orbit origin our ouster outdoor outlook oyster packaging paid pan park parks passage patriot
pattern peace people peoples perfect performance perimeter perspective pharma pirate platinum plug pool pop popular
porch post postal precision preferred premium price primo principal priority private professional prospect
prosperity provident pursuit quantum quartz radiant rail rain range rank rapid rare reading ready real reborn red
reflect regal regency regenerative regional regions rein reinsurance relay relevant reliability reliance renew rent
repay research reserve reservoir resolution resources restaurant revelation revival revolution rhino rhythm ribbon
rice right ring riot river robot root royalty rubber runway rush saddle safeguard safety savers scholar sci science
scientific scientist screen seafarer security seek select selective serve service seven shake sharing shoe shore
shoulder shuttle silence simply site six sixth sky skyline sleep slide snow soar social society software solo sound
source southeast southwest space special spectrum spring start steel stem stock stone strata strategic strive
structure structured studio summit sunshine superstar surf surge surgery synergy table tactical take tap tech
telecom telephone ten thesis third three thunder tiny token toll torrid track tractor trade transit transportation
travel trees trifecta trio triple triumph troops turn turning turtle tutor twin twist two ultra under universe
unlimited unusual uranium urban variant venture versus via video village visionary waste waters wealth wearable weed
wheeler wheels where white willow winners winning work worldwide wrap yatra zone
"""
EVERYDAY_NAME_WORDS = frozenset(_MEASURED.split()) | frozenset({
    # not measured: months and days (「Nov. 16」 is not NOV Inc), and 「news」 (News Corp; written 「News」 in outlet
    # names far more often than in lower case)
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "january", "february",
    "april", "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "news",
})
# Abbreviations headlines use that are also tickers or short company names (「AI stocks」 is not C3.ai, 「ESG rules」
# not ESGH): such a ticker counts only as ``$AI`` or ``NYSE: AI`` (not 「AI stock」 or 「(AI)」), such a name only with
# company context.
ABBREVIATIONS = frozenset({
    "AI", "AGI", "API", "AR", "VR", "IT", "EV", "EVS", "ESG", "IPO", "ETF", "ETFS", "CEO", "CFO", "CPI", "PPI", "GDP",
    "PC", "TV", "US", "UK", "EU", "USA", "UN", "LNG", "SPAC", "OPEC", "FDA", "SEC", "FTC", "DOJ", "IRS", "FBI", "CIA",
    "NFL", "NBA", "GOP", "DNA", "RNA", "LLM", "VC", "PE", "HR", "NHS", "BBC", "CNN",
})
