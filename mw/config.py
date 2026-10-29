"""What the wall shows: sector groups, tickers, news queries and seasonal narratives.

Every number on the display is computed from price history at build time. The
"why" text below is the commonly cited explanation for each seasonal pattern;
it is context for the computed stats, not a source of them.
"""

# name, kind (index/etf/future), optional GitHub fallback (real data, used only
# when Yahoo/Stooq are unreachable)
INSTRUMENTS = {
    "^GSPC": {"name": "S&P 500", "kind": "index", "fallback": "sp500_shiller"},
    "SPY":   {"name": "S&P 500 ETF", "kind": "etf"},
    "IWM":   {"name": "Russell 2000 small caps", "kind": "etf"},
    "^VIX":  {"name": "VIX volatility index", "kind": "index", "fallback": "vix_daily", "no_odds": True},
    "XLK":   {"name": "Technology", "kind": "etf"},
    "SMH":   {"name": "Semiconductors", "kind": "etf"},
    "QQQ":   {"name": "Nasdaq-100", "kind": "etf"},
    "XLC":   {"name": "Communication services", "kind": "etf"},
    "XLE":   {"name": "Energy", "kind": "etf"},
    "XOP":   {"name": "Oil & gas E&P", "kind": "etf"},
    "CL=F":  {"name": "WTI crude oil", "kind": "future", "fallback": "wti_daily"},
    "NG=F":  {"name": "Natural gas", "kind": "future", "fallback": "natgas_daily"},
    "XME":   {"name": "Metals & mining", "kind": "etf"},
    "COPX":  {"name": "Copper miners", "kind": "etf"},
    "XLB":   {"name": "Materials", "kind": "etf"},
    "HG=F":  {"name": "Copper", "kind": "future"},
    "GDX":   {"name": "Gold miners", "kind": "etf"},
    "GC=F":  {"name": "Gold", "kind": "future", "fallback": "gold_monthly", "start": 1975},
    "SI=F":  {"name": "Silver", "kind": "future"},
    "XLF":   {"name": "Financials", "kind": "etf"},
    "KRE":   {"name": "Regional banks", "kind": "etf"},
    "XLV":   {"name": "Health care", "kind": "etf"},
    "XBI":   {"name": "Biotech", "kind": "etf"},
    "XLI":   {"name": "Industrials", "kind": "etf"},
    "ITA":   {"name": "Aerospace & defense", "kind": "etf"},
    "XLY":   {"name": "Consumer discretionary", "kind": "etf"},
    "XRT":   {"name": "Retail", "kind": "etf"},
    "XLP":   {"name": "Consumer staples", "kind": "etf"},
    "XLU":   {"name": "Utilities", "kind": "etf"},
    "VNQ":   {"name": "Real estate (REITs)", "kind": "etf"},
    "TLT":   {"name": "20y+ Treasuries", "kind": "etf"},
    # inputs to the sentiment gauge only
    "^VIX3M": {"name": "3-month VIX", "kind": "index", "no_odds": True},
    "HYG":   {"name": "High-yield bonds", "kind": "etf", "no_odds": True},
    "IEF":   {"name": "7-10y Treasuries", "kind": "etf", "no_odds": True},
}

# Sector ETFs whose breadth and 52-week positions feed the sentiment gauge
SENTIMENT_SECTORS = ["XLK", "XLE", "XME", "XLB", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "VNQ", "XLC"]

# Market-moving news themes for the events radar. `gdelt` uses GDELT's query syntax (OR lists in
# parentheses, words of 3+ letters); `google` is the Google News fallback for headlines.
THEMES = [
    {"id": "war", "name": "War & geopolitics",
     "gdelt": '(war OR missile OR airstrike OR invasion OR ceasefire OR "military strike")',
     "google": "war OR missile OR airstrike OR invasion OR ceasefire"},
    {"id": "trump", "name": "Trump & Washington",
     "gdelt": '(Trump OR "White House" OR "executive order" OR Congress)',
     "google": 'Trump OR "White House" OR "executive order"'},
    {"id": "trade", "name": "Tariffs & trade",
     "gdelt": '(tariff OR tariffs OR "trade war" OR "export controls" OR sanctions)',
     "google": 'tariffs OR "trade war" OR "export controls"'},
    {"id": "fed", "name": "Fed & inflation",
     "gdelt": '("Federal Reserve" OR "Fed chair" OR "interest rates" OR inflation)',
     "google": '"Federal Reserve" OR "interest rates" OR inflation'},
    {"id": "tech", "name": "Tech & AI",
     "gdelt": '("artificial intelligence" OR Nvidia OR OpenAI OR semiconductor OR "big tech")',
     "google": '"artificial intelligence" OR Nvidia OR semiconductor OR "big tech"'},
    {"id": "economy", "name": "Economy & jobs",
     "gdelt": '(recession OR unemployment OR layoffs OR "jobs report" OR GDP)',
     "google": 'recession OR unemployment OR layoffs OR "jobs report"'},
    {"id": "energy", "name": "Oil & energy",
     "gdelt": '(OPEC OR "oil prices" OR "crude oil" OR "natural gas prices")',
     "google": 'OPEC OR "oil prices" OR "crude oil"'},
    {"id": "markets", "name": "Stock market",
     "gdelt": '("stock market" OR "Wall Street" OR "S&P 500" OR Nasdaq)',
     "google": '"stock market" OR "Wall Street" OR "S&P 500"'},
]

# Benchmark for relative strength
BENCHMARK = "SPY"
BENCHMARK_FALLBACK = "^GSPC"

# Seasonality stats for the S&P start here (the Stock Trader's Almanac convention).
SP500_SINCE = 1950

# window = (first month, number of months). Stats for each window are computed
# live; the group card shows whichever narrative overlaps the coming months.
GROUPS = [
    {
        "id": "market", "name": "Broad market", "members": ["^GSPC", "IWM"],
        "news": '"stock market" OR "S&P 500" OR "Wall Street"',
        "narratives": [
            {"window": (11, 3), "title": "Nov–Jan year-end strength",
             "why": "Holiday spending, year-end bonuses and new-year 401(k)/pension inflows get put to work; "
                    "tax-loss selling finishes in December and money is reinvested in January; fund managers "
                    "window-dress books; strategists publish upbeat annual outlooks."},
            {"window": (11, 6), "title": "The 'best six months' (Nov–Apr)",
             "why": "Most of the S&P's long-run gain has historically come between November and April: "
                    "inflows cluster around year-end and tax season, and volume and conviction fade in summer."},
            {"window": (5, 6), "title": "'Sell in May' (May–Oct)",
             "why": "Lighter summer volume, fewer catalysts between earnings seasons, and September's "
                    "repositioning historically leave May–Oct with weaker average returns."},
            {"window": (9, 1), "title": "September, historically the weakest month",
             "why": "Portfolio managers return from summer and rebalance; many mutual funds end their fiscal "
                    "year on Oct 31 and harvest losses; corporate bond and equity issuance picks up."},
        ],
    },
    {
        "id": "tech", "name": "Technology", "members": ["XLK", "SMH", "QQQ", "XLC"],
        "news": '"tech stocks" OR "semiconductor stocks" OR Nasdaq OR "AI stocks"',
        "narratives": [
            {"window": (10, 4), "title": "Oct–Jan tech season",
             "why": "Holiday device sales, enterprise IT budgets being spent before calendar year-end, CES in "
                    "early January and full-year guidance make Q4 into January the busiest stretch for tech."},
            {"window": (7, 3), "title": "Summer lull (Jul–Sep)",
             "why": "Fewer product catalysts; the September phone/product launches are often 'sell the news' events."},
        ],
    },
    {
        "id": "energy", "name": "Energy", "members": ["XLE", "XOP", "CL=F", "NG=F"],
        "news": '"oil prices" OR "energy stocks" OR OPEC OR "natural gas prices"',
        "narratives": [
            {"window": (2, 3), "title": "Spring run-up into driving season",
             "why": "Refinery maintenance ends, refiners switch to summer-blend gasoline and stock up ahead of "
                    "the Memorial Day–Labor Day driving season, which lifts crude demand."},
            {"window": (8, 3), "title": "Hurricane season risk (Aug–Oct)",
             "why": "Atlantic hurricane season (peak Aug–Oct) threatens Gulf of Mexico production and refining, "
                    "adding a supply-risk premium; gasoline demand then fades after Labor Day."},
            {"window": (11, 3), "title": "Winter: heating season & OPEC+",
             "why": "Natural gas and heating oil demand peaks Dec–Feb; OPEC+ usually meets around late "
                    "November/early December to set next year's output, a recurring event risk for crude."},
        ],
    },
    {
        "id": "mining", "name": "Mining & metals", "members": ["XME", "COPX", "XLB", "HG=F"],
        "news": '"mining stocks" OR "copper price" OR "iron ore" OR "metals prices"',
        "narratives": [
            {"window": (12, 4), "title": "China restocking (Dec–Mar)",
             "why": "Fabricators and mills restock industrial metals around Lunar New Year ahead of China's spring "
                    "construction season, the biggest swing factor in copper and iron-ore demand."},
            {"window": (5, 3), "title": "Summer demand lull",
             "why": "After the spring build, Chinese construction activity and metals buying typically slow "
                    "through the hot, rainy summer months."},
        ],
    },
    {
        "id": "gold", "name": "Gold & precious", "members": ["GDX", "GC=F", "SI=F"],
        "news": '"gold price" OR "gold miners" OR "silver price" OR "central bank gold"',
        "narratives": [
            {"window": (12, 2), "title": "Dec–Jan jewellery & festival demand",
             "why": "Indian wedding season, Lunar New Year gift buying in China and jewellers restocking after the "
                    "holidays concentrate physical demand around the turn of the year."},
            {"window": (8, 2), "title": "Late-summer build into Diwali",
             "why": "Dealers stock up ahead of India's festival season (Dhanteras and Diwali in Oct/Nov), "
                    "historically supporting gold in August–September."},
            {"window": (3, 3), "title": "Spring soft patch (Mar–May)",
             "why": "Once festival and new-year demand passes, physical buying slows until the late-summer restock."},
        ],
    },
    {
        "id": "financials", "name": "Financials", "members": ["XLF", "KRE"],
        "news": '"bank stocks" OR "financial stocks" OR "bank earnings"',
        "narratives": [
            {"window": (10, 3), "title": "Q4: year-end strength & rate expectations",
             "why": "Banks are cyclical and rate-sensitive: they tend to move with the broad market's year-end "
                    "strength and with steeper yield curves, which widen lending margins."},
            {"window": (7, 1), "title": "July: capital-return announcements",
             "why": "Fed stress-test results land in late June; banks then announce buybacks and dividend hikes, "
                    "alongside Q2 earnings from the big banks in mid-July."},
        ],
    },
    {
        "id": "health", "name": "Health care", "members": ["XLV", "XBI"],
        "news": '"healthcare stocks" OR "biotech stocks" OR "pharma stocks" OR FDA',
        "narratives": [
            {"window": (1, 1), "title": "January biotech deal season",
             "why": "Small-cap biotech often benefits from the January effect, and the J.P. Morgan Healthcare "
                    "Conference in mid-January concentrates deal announcements and guidance."},
            {"window": (9, 2), "title": "Defensive in the autumn wobble",
             "why": "Health care is a classic defensive: demand doesn't depend on the economy, so it tends to "
                    "hold up better when the broad market is weak (historically Sep–Oct)."},
        ],
    },
    {
        "id": "industrials", "name": "Industrials", "members": ["XLI", "ITA"],
        "news": '"industrial stocks" OR "manufacturing PMI" OR "defense stocks" OR "aerospace stocks"',
        "narratives": [
            {"window": (10, 7), "title": "Cyclical Oct–Apr strength",
             "why": "Industrials follow the 'best six months' pattern closely: year-end capex budgets, new-year "
                    "order books and the spring construction and transport season."},
        ],
    },
    {
        "id": "consumer", "name": "Consumer", "members": ["XLY", "XRT"],
        "news": '"retail sales" OR "consumer stocks" OR "consumer spending" OR "holiday sales"',
        "narratives": [
            {"window": (10, 3), "title": "Holiday shopping season",
             "why": "Retailers and discretionary names rally into Black Friday and Cyber Monday as investors "
                    "position for holiday sales data; January then brings the 'post-holiday hangover' results."},
            {"window": (2, 3), "title": "Tax-refund spending (Feb–Apr)",
             "why": "US tax refunds land from mid-February, giving consumer spending a seasonal lift into spring."},
        ],
    },
    {
        "id": "defensives", "name": "Defensives", "members": ["XLP", "XLU"],
        "news": '"utility stocks" OR "consumer staples" OR "defensive stocks"',
        "narratives": [
            {"window": (5, 6), "title": "Relative safety in May–Oct",
             "why": "Staples and utilities have steady demand and bond-like dividends; investors rotate into "
                    "them during the historically weaker summer-autumn stretch and when volatility rises."},
            {"window": (7, 3), "title": "Summer cooling demand",
             "why": "Peak air-conditioning load lifts utility volumes in July–September; utilities also rally "
                    "when bond yields fall."},
        ],
    },
    {
        "id": "rates", "name": "Real estate & rates", "members": ["VNQ", "TLT"],
        "news": '"Treasury yields" OR REITs OR "mortgage rates" OR "Federal Reserve"',
        "narratives": [
            {"window": (11, 3), "title": "Year-end rate repricing",
             "why": "REITs and long bonds move inversely to long-term yields; December's Fed meeting and "
                    "year-end positioning often reset rate expectations for the new year."},
            {"window": (5, 4), "title": "Summer flight-to-safety",
             "why": "Long Treasuries tend to rally when equities wobble or growth expectations fall, which has "
                    "historically clustered in the weaker summer-autumn months."},
        ],
    },
]

# Month-by-month almanac for the S&P 500 (the stats beside each note are computed).
SP500_MONTH_NOTES = {
    1: "January effect: new-year inflows; 'as January goes, so goes the year' (the January barometer).",
    2: "Often choppy after January; post-earnings lull.",
    3: "Quarter-end rebalancing and triple witching.",
    4: "Historically one of the strongest months: tax-season liquidity and Q1 earnings.",
    5: "'Sell in May': the start of the historically weaker six months.",
    6: "Often soft; quarter-end rebalancing, Russell reconstitution and Fed stress tests.",
    7: "Historically firm: Q2 earnings season and early-month inflows.",
    8: "Thin summer volume; volatility spikes have clustered here (2015, 2019, 2024).",
    9: "Historically the weakest month: post-summer repositioning and fund year-end tax selling.",
    10: "The most volatile month (1929, 1987, 2008), yet a frequent 'bear-killer' where corrections end.",
    11: "Start of the 'best six months': holiday spending and post-election relief rallies.",
    12: "Santa Claus rally window; tax-loss selling ends; year-end window dressing.",
}

# The Fed's published 2026 schedule plus its tentative 2027 dates (decision day = 2nd day).
FOMC = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28",
]

FIXED_EVENTS = [
    ("2026-11-08", "Diwali: Indian festival gold buying peaks", "gold"),
    ("2027-02-06", "Lunar New Year: China metals restocking season", "mining"),
    ("2027-10-29", "Diwali", "gold"),
]
