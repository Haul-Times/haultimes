"""
HaulTimes editorial rules: what gets on the site, which topic it goes in,
how important it is, and which copies of the same story to hide.

Used by fetch_news.py (when stories come in, and to re-check every stored
story on each run) and by build_site.py (so the homepage, topic pages and
feeds all show exactly the same set of stories).

Nothing here deletes a stored story. A story that fails the rules is kept
with  status = "rejected" | "review" | "duplicate"  and a list of reasons,
so the rules can be changed later and everything re-checked.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERRIDES_FILE = os.path.join(ROOT, "overrides.json")

SHOWN = "ok"

# ------------------------------------------------------------------ sources
# Tier 1: trucking trade press with their own reporters, plus government sources.
# Tier 2: smaller trucking outlets and major national news.
# Tier 3: everyone else (local news etc.). Tier 4: low-quality / SEO / aggregators.
TIER1 = ["freightwaves", "transport topics", "ttnews", "commercial carrier journal", "ccj", "overdrive",
         "heavy duty trucking", "truckinginfo", "trucking info", "truck news", "trucknews", "today's trucking",
         "todays trucking", "fleetowner", "fleet owner", "journal of commerce", "joc", "land line", "landline",
         "trucking dive", "supply chain dive", "dat freight", "act research", "fmcsa", "u.s. department of transportation",
         "transport canada", "cbsa", "canada border services", "u.s. customs and border protection", "cbp.gov",
         "american trucking associations", "canadian trucking alliance", "ontario trucking association", "ooida"]
TIER2 = ["thetrucker", "the trucker", "truckers news", "cdllife", "cdl life", "etrucker", "fleet equipment",
         "bulk transporter", "trailer/body builders", "trailer body builders", "trucking dive", "logistics management",
         "dc velocity", "supplychainbrain", "reuters", "associated press", "ap news", "bloomberg", "wall street journal",
         "cnbc", "cbc", "ctv", "global news", "globe and mail", "financial post", "the canadian press", "npr",
         "new york times", "washington post", "los angeles times", "toronto star", "national post", "fox business",
         "abc news", "cbs news", "nbc news", "usa today", "politico", "axios", "marketplace", "insideevs", "electrek"]
TIER4 = ["good men project", "ritz herald", "hoodline", "24/7 wall st", "marketscale", "scanx", "fast food club",
         "thetravel", "the travel", "newsbreak", "msn", "yahoo", "ntd", "the epoch times", "indexbox",
         "openpr", "einpresswire", "ein presswire", "medium", "substack", "techbullion", "digital journal",
         "kalkine", "simply wall st", "marketbeat", "zacks", "motley fool", "fool.com", "investorplace",
         "benzinga", "seeking alpha", "gurufocus", "stocktitan", "stock titan", "tipranks", "investing.com",
         "nasdaq.com", "investor's business daily", "ainvest", "finimize"]
# Sources that are almost entirely stock commentary, market-research sales pages or press-release wires.
FINANCE_SOURCES = ["kalkine", "simply wall st", "marketbeat", "zacks", "motley fool", "fool.com", "investorplace",
                   "gurufocus", "stocktitan", "stock titan", "tipranks", "ainvest", "finimize"]
RESEARCH_SOURCES = ["indexbox", "openpr", "market research future", "marketsandmarkets", "grand view research",
                    "fortune business insights", "precedence research", "allied market research", "research and markets",
                    "mordor intelligence", "imarc", "verified market"]
WIRE_SOURCES = ["pr newswire", "prnewswire", "business wire", "businesswire", "globenewswire", "globe newswire",
                "accesswire", "einpresswire", "ein presswire", "newswire", "prweb", "newsfile", "cision", "openpr"]
# Trucking outlets in other countries (their headlines rarely say which country).
UK_WORDS = ["pence", "petrol", "motorists", "dvla", "mot test", "fuel duty", "a-road", "m25", "m6 ", "nhs",
            "council tax", "sainsbury", "tesco", "asda", "rac ", "aa says", "quid"]
FOREIGN_SOURCES = ["daily express", "express.co.uk", "daily mail", "the sun", "daily mirror", "mirror", "gb news",
                   "the independent", "the telegraph", "telegraph", "the guardian", "bbc", "sky news", "metro.co.uk",
                   "birmingham live", "manchester evening news", "wales online", "chronicle live", "telesur", "mercopress", "buenos aires times", "rio times", "bnamericas", "prensa latina",
                   "sa trucker", "australasian transport", "prime mover", "big rigs", "owner//driver", "owner driver",
                   "fullyloaded", "fully loaded", "trailer magazine", "deliver magazine", "motor transport",
                   "road transport", "commercial motor", "transport engineer", "logistics manager", "nri affairs",
                   "ghanaweb", "new indian express", "times of india", "hindustan times", "economic times", "et infra",
                   "etinfra", "financial express", "business standard", "livemint", "mint", "moneycontrol",
                   "haberler", "manila bulletin", "inquirer.net", "the star malaysia", "bernama", "dawn", "the hindu",
                   "punch newspapers", "premium times", "daily maverick", "news24", "stuff.co.nz",
                   "nz herald", "abc australia", "the age", "sydney morning herald", "al circle", "energynow",
                   "gcaptain", "splash247", "lloyd's list", "tradewinds", "seatrade", "hellenic shipping",
                   "the loadstar", "air cargo news", "aircargo week", "railway age", "trains magazine", "ship & bunker"]

# Canada-US trade measures that change what crosses the border by truck.
TRADE_NA = ["tariff relief", "counter-tariff", "counter-tariffs", "surtax", "cusma", "usmca", "cbsa", "eManifest",
            "ace manifest", "fast card", "port of entry", "ports of entry", "customs broker", "remission"]
OFFICIAL_SOURCES = ["federal register", "transport canada", "fmcsa", "cbp.gov", "cbsa"]
TRUCKING_SOURCES = TIER1 + ["thetrucker", "the trucker", "truckers news", "cdllife", "cdl life", "etrucker",
                            "fleet equipment", "bulk transporter", "trailer/body builders", "trailer body builders"]


_RX = {}


def _rx(words):
    """Match whole words: 'dies' must not match 'diesel'. Longer entries (6+ letters)
    also match their plural/-ing forms ('bankrupt' -> 'bankruptcy')."""
    key = tuple(words)
    if key not in _RX:
        parts = []
        for w in words:
            w = w.strip().lower()
            if not w:
                continue
            if not re.search(r"[a-z0-9]", w):
                parts.append(re.escape(w))
                continue
            left = r"(?<![a-z0-9])" if w[0].isalnum() else ""
            right = r"(?![a-z0-9])" if (len(w) < 6 and w[-1].isalnum()) else ""
            parts.append(left + re.escape(w) + right)
        _RX[key] = re.compile("|".join(parts) or r"(?!x)x")
    return _RX[key]


def _has(text, words):
    return bool(_rx(words).search(text.lower()))


def _hits(text, words):
    return [m.group(0) for m in _rx(words).finditer(text.lower())]


def source_tier(source):
    s = (source or "").lower()
    if _has(s, TIER1):
        return 1
    if _has(s, TIER4):
        return 4
    if _has(s, TIER2):
        return 2
    return 3


def is_trucking_source(source):
    return _has((source or "").lower(), TRUCKING_SOURCES)


# ------------------------------------------------------------------ word lists
# Words that only make sense for US/Canadian commercial road freight.
STRONG = ["camionnage", "camionneur", "camionneurs", "camionneuse", "transport routier", "poids lourds",
          "véhicules lourds", "trucking", "trucker", "truckers", "truckload", "less-than-truckload", "ltl ", " ltl", "fmcsa", "cdl",
          "owner-operator", "owner operator", "freight broker", "freight brokerage", "semi truck", "semi-truck",
          "semitruck", "tractor-trailer", "tractor trailer", "big rig", "18-wheeler", "class 8", "cvsa",
          "out of service", "out-of-service", "electronic logging", " eld", "hours of service", "hours-of-service",
          "drayage", "reefer", "flatbed", "dry van", "transport truck", "commercial vehicle", "commercial truck",
          "truck driver", "truck drivers", "truck stop", "truck parking", "weigh station", "spot rate",
          "contract rate", "freight market", "freight rates", "freight recession", "freight demand", "freight volumes",
          "load board", "load-to-truck", "tender rejection", "dispatcher", "motor carrier", "carriers",
          "fleets", "fleet ", "heavy-duty", "heavy duty", "teamsters", "ooida", "american trucking",
          "canadian trucking", "ontario trucking", "driver inc", "cargo theft", "double brokering", "double-brokering",
          "freight fraud", "stolen loads", "truck tolls", "intermodal", "act expo", "tesla semi", "electric truck",
          "battery-electric truck", "hydrogen truck", "autonomous truck", "self-driving truck", "trucks",
          "cbsa", "cbp ", " cbp", "customs", "usmca", "cusma", "freight hub", "truck output", "truck sales",
          "truck orders", "trailer orders", "truckmaker", "truck maker", "trailer", "diesel price", "diesel prices",
          "diesel stockpile", "diesel supply", "diesel shortage", "diesel tax", "diesel order", "diesel inventories",
          "$6 diesel", "$5 diesel", "high diesel", "fuel surcharge", "border crossing", "border services agency",
          "port of entry", "ports of entry", "commercial lanes", "truck lanes", "ambassador bridge",
          "blue water bridge", "peace bridge", "gordie howe", "lewiston-queenston", "commercial vehicles", "drayage"]
CARRIERS = ["fedex freight", "ups ", "tforce", "old dominion", "j.b. hunt", "jb hunt", "knight-swift", "werner",
            "schneider", "xpo", "saia", "estes", "landstar", "c.h. robinson", "ch robinson", "rxo", "uber freight",
            "ryder", "penske", "yellow corp", "abf freight", "arcbest", "heartland express", "marten",
            "covenant", "prime inc", "swift transportation", "tql", "total quality logistics", "coyote logistics",
            "echo global", "arrive logistics", "nfi ", "pitt ohio", "r+l carriers", "southeastern freight",
            "averitt", "daseke", "tfi international", "transforce", "mullen group", "bison transport",
            "titanium transportation", "trimac", "day & ross", "manitoulin", "kriska", "challenger motor",
            "ps logistics", "roane", "freymiller", "c.r. england", "crst", "maverick transportation", "hirschbach",
            "kenworth", "peterbilt", "freightliner", "daimler truck", "dtna", "volvo trucks", "volvo group",
            "mack trucks", "navistar", "international motors", "paccar", "western star", "great dane", "wabash",
            "utility trailer", "hyundai translead", "stoughton", "vanguard trailer", "cummins", "allison transmission",
            "eaton", "bendix", "meritor", "samsara", "motive", "platform science", "trimble", "omnitracs",
            "dat ", "truckstop", "pilot flying j", "love's", "ta petro", "nikola", "aurora innovation",
            "kodiak robotics", "plus automation", "einride", "embark trucks", "gatik"]
WEAK = ["truck", "freight", "driver", "logistics", "diesel", "carrier", "highway", "border", "supply chain",
        "warehouse", "shipping", "shipper", "cargo", "haul", "tariff", "transport", "fleet", "load"]

# ------------------------------------------------------------------ rejection rules
FOREIGN = ["india", "indian", "pakistan", "bangladesh", "sri lanka", "nepal", "philippine", "manila",
           "malaysia", "singapore", "indonesia", "vietnam", "thailand", "china", "chinese", "japan",
           "korea", "taiwan", "australia", "aussie", "new zealand", "kiwi", "nigeria", "kenya", "ghana",
           "south africa", "uganda", "tanzania", "ukraine", "russia", "dnipro", " uk ", "u.k.", "britain",
           "british", "england", "scotland", "wales", "ireland", "yorkshire", "europe", " eu ",
           "germany", "france", "spain", "italy", "poland", "netherlands", "dubai", "saudi", "uae",
           "iran", "israel", "türkiye", "turkish", "ankara", "egypt", "brazil", "argentina", "chile", "peru", "colombia",
           "hgv", "lorry", "lorries", "haulage", "sebi", " nse", " bse", "tse:", ".ns)", "railways", " ioc ",
           "berjaya", "tasco", "mnre", "arai", "fy27", "fy28", "crore", "lakh", "rupee", "naxal", "bjd",
           "lagos", "lastma", "abuja", "nairobi", "accra", "afienya", "johannesburg", "cairo", "karachi", "lahore",
           "islamabad", "delhi", "mumbai", "chennai", "kolkata", "bengaluru", "bangalore", "hyderabad",
           "dhaka", "colombo", "kathmandu", "jakarta", "kuala lumpur", "bangkok", "hanoi", "beijing",
           "shanghai", "shenzhen", "hong kong", "tokyo", "seoul", 
           "auckland", 
           "madrid", "warsaw", "kyiv", "moscow", "istanbul", "riyadh", "tehran", "sao paulo",
           "nigerian", "kenyan", "pakistani", "bangladeshi", "filipino", "malaysian", "australian", "european",
           "german ", "french ", "polish ", "fenerbah", "galatasaray", "west asia", "middle east", " n3 ",
           "natroad", "nhvr", "dvsa", "logistics uk", "road haulage association", "rha ",
           # Latin America (Mexico stays: cross-border trucking with the US)
           "chilean", "santiago de chile", "peruvian", "colombian", "bogota", "brazilian", "argentine",
           "argentinian", "buenos aires", "venezuela", "venezuelan", "ecuador", "ecuadorian", "bolivia", "bolivian",
           "uruguay", "uruguayan", "paraguay", "paraguayan", "guatemala", "guatemalan", "honduras", "honduran",
           "el salvador", "salvadoran", "nicaragua", "costa rica", "latin america", "south america", "caribbean",
           "cuba", "cuban", "haiti", "dominican republic",
           # more countries and demonyms
           "japanese", "korean", "thai", "vietnamese", "indonesian", "philippines", "italian", "dutch truck",
           "belgium", "belgian", "sweden", "swedish", "norway", "norwegian", "denmark", "danish", "finland",
           "finnish", "austria", "austrian", "switzerland", "swiss", "irish", "scottish", "ukrainian", "russian",
           "romania", "romanian", "hungary", "hungarian", "greece", "czech", "slovak", "lithuania", "latvia",
           "estonia", "israeli", "egyptian", "south african", "ghanaian", "ethiopia", "zimbabwe", "zambia",
           "morocco", "algeria", "tunisia", "qatar", "kuwait", "oman", "bahrain", "lebanon", "iraq"]
MUSIC = ["drive-by truckers", "drive by truckers", "driveby truckers", "concert", "tour dates", " album",
         "homecoming show", "setlist", "band ", "live music", "songwriter", "music hall", "revolution hall",
         "ryman", "festival lineup", "tickets on sale", "on tour"]
CONSUMER = ["pickup", "pick-up", "f-150", "f150", "silverado", "sierra 1500", "ram 1500", "ram 2500", "tacoma",
            "tundra", "ranger raptor", "raptor r", "cybertruck", "rivian r1t", "lightning", "maverick hybrid",
            "colorado zr2", "gladiator", "hilux", "frontier", "ridgeline", "food truck", "monster truck",
            "ice cream truck", "toy truck", "fire truck", "garbage truck toy", "sedan", "suv", "minivan",
            "car insurance", "auto insurance", "insurance claims both", "bbq", "barbecue", "restaurant",
            "diner", "recipe", "route 66", "road trip", "tourists", "swear by", "best places to eat",
            "camper", "rv ", "overland", "towing capacity", "truck bed", "lift kit", "harbor freight",
            "christmas gift", "gifts for", "deal of the day", "ho gauge", "model train", "toy ", "lego",
            "the finger", "viral", "celebrity", "horoscope", "football", "soccer", "transfer offer",
            "nfl", "nba", "nhl", "mlb", "touchdown"]
# "truckload of money", "truckload of protein": an idiom, not freight.
IDIOM = re.compile(r"\btruck ?loads? of (money|cash|protein|food|candy|toys|gifts|love|fun|points|goals|"
                   r"talent|wins|reasons|problems|trouble|turkeys|donations|meat|groceries|presents|books|"
                   r"supplies|coats|water|pumpkins|christmas trees|snow|laughs|cheer)\b")
FOOD_BANK = ["food bank", "food pantry", "donation", "donations", "donate", "donates", "donated", "fight hunger", "meat the need", "toy drive", "charity"]
JOBS = re.compile(r"(\bjob near\b|truck driving jobs?\b|driving job\b|\bdrivers? wanted\b|\bnow hiring\b|"
                  r"\bhiring:|\bapply (now|today)\b|\bsign[- ]on bonus\b|\bclass[- ]a cdl\b.*\b(otr|local|regional)\b|"
                  r"\bcdl[- ]a drivers?\b|\bhome daily\b|\bhome weekly\b|\bper mile\b.*\bpay\b|"
                  r"\bowner operators? needed\b|\blease purchase\b|^[A-Z]{2,5} [A-Z]{2,5} - |\bcareers? at\b|"
                  r"\bjob opening|\bjob fair\b|\bjobs? in [A-Z][a-z]+, [A-Z]{2}\b)", re.I)
STOCK = re.compile(r"(\((nasdaq|nyse|tsx|tsxv|nyse american|otc|amex|cboe)\s*:\s*[a-z.]+\)|\bstock (price|forecast|"
                   r"prediction|quote|could|to buy|to watch|rating)|\bshares? (of|jump|jumps|surge|surges|fall|falls|"
                   r"slide|slides|rise|rises|gain|gains|drop|drops|soar|soars)\b|\bprice target\b|\banalysts? "
                   r"(say|says|see|expect|rating|ratings)\b|\b(buy|sell|hold) rating\b|\breiterates?\b|"
                   r"\b(equal|over|under)weight\b|\bupgrade[sd]?\b to\b|\bdowngrade[sd]?\b|\bdividend\b|"
                   r"\bearnings call transcript\b|\bseasonal returns\b|\bshould you buy\b|\bis it a buy\b|"
                   r"\bafter a \d+% (gain|rally|drop|decline)\b|\bwhat comes next for\b|\bsurge despite\b|"
                   r"\bearnings potential\b|\bundervalued\b|\boverbought\b|\boversold\b|\b52-week\b|"
                   r"\binvestors? (should|are|cheer)\b|\bstocks? (tied|investors|that)\b|\bmorgan stanley says\b|"
                   r"\bwall street (says|sees|expects)\b|\bvaluation\b)", re.I)
RESEARCH = re.compile(r"(\bmarket (size|share|forecast|report|outlook|analysis|to reach|is expected|projected|"
                      r"growth|trends?)\b.*\b(20[2-4]\d|cagr|billion|million)\b|\bcagr\b|\bforecast to expand\b|"
                      r"\bthrough 20[3-4]\d\b|\bby 20[3-4]\d\b.*\bmarket\b|\bmarket research\b|\bindustry report\b)", re.I)
OTHER_MODE = ["ocean freight", "ocean rates", "container rates", "container shipping", "shipping rates",
              "tanker", "vlcc", "lpg carrier", "crude carrier", "bulk carrier", "dry bulk", "bulker", "vessel",
              "ship capsizes", "freight ship", "shipping line", "maersk", "msc ", "cma cgm", "hapag",
              "dp world", "suez", "red sea", "strait of hormuz", "panama canal", "bauxite", "iron ore",
              "crude discount", "oil exports", "refiners", "air cargo", "air freight", "airfreight", "cargo jet",
              "freighter aircraft", "baltic dry", "drewry", "xeneta", "scfi", "wci ", "teu", "bunker fuel",
              "charter rates"]
# When one of these is present, an ocean/rail/air story may still matter to North American trucking.
NA_LINK = ["truck", "trucking", "drayage", "intermodal", "chassis", "port of los angeles", "port of long beach",
           "los angeles", "long beach", "port of oakland", "port of seattle", "port of tacoma", "savannah",
           "port of new york", "new jersey", "houston", "charleston", "norfolk", "port of vancouver",
           "prince rupert", "port of montreal", "halifax", "us ports", "u.s. ports", "canadian ports",
           "east coast ports", "west coast ports", "ila ", "ilwu", "rail strike", "cn rail", "cpkc", "union pacific",
           "bnsf", "csx", "norfolk southern", "cross-border", "border", "usmca", "cusma", "tariff"]
NA_PLACES = ["u.s.", "us", "usa", "america", "american", "canada", "canadian", "north america", "mexico",
             "usmca", "cusma", "ontario", "quebec", "alberta", "british columbia", "manitoba", "saskatchewan",
             "nova scotia", "new brunswick", "texas", "california", "florida", "ohio", "michigan", "illinois",
             "new york", "georgia", "tennessee", "pennsylvania", "fmcsa", "cbp", "cbsa"]
MALFORMED = re.compile(r"(^\s*[-–|:]|\barchives?$|^(truckload|ltl|logistics|freight|trucking|news|latest) "
                       r"(freight )?(news|archives?)$|^\W*$|^page \d+|^home$|^untitled|^(category|tag|topic):)", re.I)
CRIME_MINOR = ["arrested", "dui", "dwi", "charged with", "sentenced", "pleads guilty", "stolen car", "shooting",
               "stabbing", "murder"]
INCIDENT = ["crash", "crashes", "collision", "rollover", "rolls over", "overturn", "runs off road", "jackknife",
            "fire on", "catches fire", "spill", "plane clips", "near miss", "pileup", "pile-up", "struck by",
            "slams into", "killed", "dies", "fatal", "injured", "traffic advisory", "lanes closed",
            "road closed", "detour"]
# An incident becomes a real operations story when it closes a major freight route.
DISRUPTION = ["shut down", "shutdown", "closed for", "closure", "closed", "diverted", "bridge", "border crossing",
              "interstate", "highway 401", "trans-canada",
              "trans canada", "bridge closed", "border crossing closed", "hours-long", "miles-long", "days",
              "detours for trucks", "hazmat"]
HUMAN_INTEREST = ["enjoys", "award", "honored", "honoured", "highway angel", "wins ", "winner", "voting underway",
                  "contest", "road warrior", "spotlight", "meet the", "celebrates", "retires", "veteran of the year",
                  "transition trucking", "truck show", "parade", "christmas convoy", "wreaths across america",
                  "third generation", "family tradition"]
EVENT = ["agenda", "expo", "conference", "summit", "webinar", "trade show", "awards"]
ROUNDUP = ["biggest trucking industry headlines", "headlines this week", "week in review", "news roundup",
           "this week in trucking", "top stories this week", "what you missed"]
ANNOUNCE = re.compile(r"^[A-Z][\w&.\-' ]{1,40}?\b(launches|introduces|unveils|announces|debuts|rolls out|"
                      r"partners with|teams with|teams up with|expands|opens|names|appoints|hires|selects|"
                      r"adds|releases|offers)\b", re.I)
GOV = ["fmcsa", "dot", "transport canada", "cbsa", "cbp", "ministry", "government", "province", "state of",
       "congress", "senate", "parliament", "court", "agency", "department", "u.s.", "federal", "ontario",
       "quebec", "alberta", "british columbia", "manitoba", "saskatchewan", "texas", "california"]
LEGAL_MARKETING = ["truck accident lawyer", "truck accident attorney", "injury lawyer", "injury attorney",
                   "who else pays", "who pays for a truck crash", "after a truck accident", "compensation for your",
                   "law firm", "free consultation"]
SPONSORED = ["sponsored", "paid post", "partner content", "advertorial", "brought to you by", "presented by"]

# ------------------------------------------------------------------ categories
# Each topic gets points from its words; the story goes where it scores highest.
# Phrases score more than single words, so one stray word can't decide the topic.
CAT_WORDS = {
    "rates": {3: ["spot rate", "spot rates", "contract rate", "contract rates", "truckload rates", "ltl rates",
                  "freight rates", "freight market", "freight demand", "freight volumes", "freight recession",
                  "capacity", "tender rejection", "load-to-truck", "load to truck", "cass freight index",
                  "freight index", "rate per mile", "trucking recovery", "freight recovery", "peak season",
                  "produce season", "load volumes", "shipment volumes", "truckload market", "freight cycle",
                  "operating ratio", "cost per mile"],
              1: ["rates", "demand", "volumes", "market", "recovery", "pricing", "shippers", "spot", "tonnage",
                  "loads", "economy", "consumer spending", "imports", "retail sales"]},
    "border": {3: ["cross-border", "cross border", "border crossing", "border crossings", "cbsa", "cbp",
                   "customs", "tariff", "tariffs", "usmca", "cusma", "ambassador bridge", "gordie howe",
                   "blue water bridge", "peace bridge", "laredo", "port of entry", "ports of entry",
                   "border wait", "border waits", "foreign-trade zone", "foreign trade zone", "fast card",
                   "free trade", "trade war", "duties", "border services", "border security", "seizes", "seized",
                   "mexican trucks", "cabotage"],
               1: ["border", "canada-u.s", "u.s.-canada", "us-canada", "canada", "mexico", "mexican", "trade",
                   "import", "export"]},
    "regs": {3: ["fmcsa", "regulation", "regulations", "rule", "rulemaking", "final rule", "proposed rule",
                 "eld", "electronic logging", "hours of service", "hours-of-service", "drug and alcohol",
                 "clearinghouse", "english proficiency", "english-language", "non-domiciled", "cdl rules",
                 "speed limiter", "out of service", "out-of-service", "inspection", "inspections", "enforcement",
                 "crackdown", "compliance", "safety rating", "csa score", "audit", "lawsuit", "court", "ruling",
                 "supreme court", "nuclear verdict", "verdict", "liability", "legislation", "bill ", "congress",
                 "senate", "parliament", "ministry of transportation", "transport canada", "dot ", "u.s. dot",
                 "nhtsa", "epa", "carb", "emissions rule", "emissions standards", "mandate", "complaint",
                 "violations", "pilot program", "brake safety week", "roadcheck", "operation safe driver",
                 "policy", "budget", "tax break", "tax breaks", "driver inc", "misclassification", "cvsa",
                 "license", "licence", "registration", "broker transparency", "mc number", "usdot number"],
             1: ["safety", "law", "federal", "state", "province", "government", "officials", "oversight",
                 "operation", "removes", "sweep", "checkpoint", "roads", "police", "troopers",
                 "legal", "rules", "ban", "fine", "fines", "penalty", "permits"]},
    "fuel": {3: ["diesel price", "diesel prices", "diesel fuel price", "fuel price", "fuel prices", "fuel tax",
                 "fuel taxes", "gas tax", "fuel surcharge", "diesel stockpile", "diesel stockpiles",
                 "diesel inventories", "diesel supply", "diesel shortage", "$6 diesel", "$5 diesel", "$4 diesel",
                 "diesel order", "fuel costs", "carbon tax", "diesel tax", "pump prices", "eia", "refinery",
                 "renewable diesel", "biodiesel", "high diesel", "diesel hits", "diesel climbs", "diesel falls",
                 "diesel drops"],
             1: ["diesel", "fuel", "gallon", "litre", "oil prices", "crude", "opec", "gasoline"]},
    "equip": {3: ["class 8 orders", "class 8 sales", "truck orders", "truck sales", "trailer orders",
                  "truck output", "truck production", "range extender", "electric truck", "battery-electric",
                  "hydrogen truck", "fuel cell truck", "tesla semi", "autonomous truck", "self-driving",
                  "driverless", "recall", "recalls", "tires", "tire", "retread", "axle", "engine", "engines",
                  "transmission", "brakes", "dashcam", "dash cam", "telematics", "maintenance", "dpf", "injector",
                  "aftertreatment", "trailer", "trailers", "reefer unit", "tractor", "dealer", "dealership",
                  "spec'ing", "technology", "software", "app ", "fuel supplement", "additive", "charging",
                  "chargers", "megawatt", "battery"],
              1: ["equipment", "truck", "trucks", "model", "new", "test", "review", "fleet", "electric", "ev", "kenworth",
                  "peterbilt", "freightliner", "volvo", "mack", "navistar", "western star", "cummins", "allison",
                  "eaton", "wabash", "great dane", "utility trailer", "dtna", "daimler"]},
    "drivers": {3: ["driver pay", "drivers' pay", "driver wages", "wages", "pay raise", "per mile pay", "cents per mile",
                    "driver shortage", "driver turnover", "driver hiring", "hiring", "recruit", "recruiting",
                    "retention", "training", "cdl school", "entry-level driver", "eldt", "apprenticeship",
                    "truck parking", "parking shortage", "working conditions", "detention time", "detention pay",
                    "strike", "strikes", "union", "unionize", "teamsters", "collective agreement", "labour dispute",
                    "labor dispute", "walkout", "lockout", "layoffs", "laid off", "job cuts", "health", "fatigue",
                    "sleep apnea", "veterans", "women in trucking", "driver of the year", "18 to 20",
                    "under-21", "young drivers", "immigrant drivers", "driver safety", "harassment"],
                1: ["driver", "drivers", "trucker", "truckers", "jobs", "workers", "pay", "employees", "career",
                    "workforce"]},
    "other": {3: ["bankrupt", "chapter 11", "chapter 7", "closes its doors",
                  "shuts down operations", "ceases operations", "acquires", "acquisition", "acquired", "merger",
                  "merge", "buys", "to buy", "sells", "sale of", "earnings", "quarterly results", "reports results",
                  "revenue", "profit", "loss", "management changes", "results",
                  "worse-than-expected", "better-than-expected", "bankruptcy", "bankruptcies", "ceo", "president", "layoff",
                  "cargo theft", "freight fraud", "double brokering", "stolen loads", "fraud", "cyberattack",
                  "ransomware", "terminal", "freight hub", "expansion", "ipo", "investment", "funding",
                  "folding", "closing", "insurance costs", "insurance premiums", "act expo", "conference",
                  "association", "trade show"],
              1: ["company", "carrier", "carriers", "broker", "brokerage", "firm", "firms", "industry", "business",
                  "deal", "costs", "fleet"]},
}
# Tie-breaker order when two topics score the same (more specific first).
CAT_ORDER = ["fuel", "border", "regs", "equip", "drivers", "rates", "other"]

# ------------------------------------------------------------------ importance
HIGH_IMPACT = {
    20: ["final rule", "new rule", "rule takes effect", "takes effect", "goes into effect", "ban", "banned",
         "strike", "walkout", "lockout", "shutdown", "shuts down", "border closed", "border closure",
         "bankruptcy", "bankruptcies", "chapter 11", "ceases operations", "closes its doors",
         "recall", "emergency declaration", "state of emergency", "cyberattack", "ransomware",
         "english proficiency", "non-domiciled", "out of service", "out-of-service", "truck lanes closed",
         "closed to trucks", "bridge closed", "lanes closed", "crossing closed", "record high", "record low",
         "23-year low", "highest since", "lowest since", "surge", "plunge", "spike", "soar"],
    12: ["fmcsa", "transport canada", "cbsa", "cbp", "usmca", "cusma", "congress", "senate", "parliament",
         "tariff", "tariffs", "supreme court", "court rules", "ruling", "verdict", "diesel prices", "diesel price", "fuel tax",
         "spot rates", "contract rates", "capacity", "driver pay", "layoffs", "acquires", "acquisition", "merger",
         "crackdown", "enforcement", "budget", "cargo theft", "freight fraud", "double brokering", "job cuts",
         "to cut", "cuts jobs", "laid off", "to acquire", "acquire", "buys", "to buy", "ambassador bridge",
         "blue water bridge", "peace bridge", "gordie howe", "lacolle", "laredo", "port huron", "lewiston-queenston"],
    6: ["proposed", "proposal", "survey", "report", "data", "index", "forecast", "outlook", "warns", "expects",
        "rising", "falling", "costs", "%", "million", "billion"],
}
NATIONAL = ["nationwide", "national", "across north america", "across the u.s", "across canada", "industry-wide",
            "america's", "u.s. ", "us ", "canada", "canadian", "federal", "trucking industry", "carriers"]


def norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"\s+[-–|]\s+[^-–|]{2,60}$", "", t)  # drop " - Publisher"
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


STOP = set("""a an the and or of to in on for with at by from as is are was were be been it its this that these
those after before over under into out up down new says say said will would could can may might more most than
then just about amid as despite via vs why what how who when where which while your you our we their they his her
truck trucks trucking trucker truckers freight carrier carriers driver drivers fleet fleets industry""".split())


GENERIC = set("""high low price pric cost rate grow rise fall put make take year week month day report data plan
show need help keep look must amid top big set get go hit cut add""".split())


def tokens(t):
    out = []
    for w in norm_title(t).split():
        if w in STOP or len(w) < 3:
            continue
        for suf in ("ings", "ing", "ies", "es", "ed", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return set(out)


def canonical_url(url):
    """Same article, different tracking tags or AMP link -> same key."""
    if not url:
        return ""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = p.netloc.lower().replace("www.", "").replace("amp.", "")
    path = re.sub(r"/(amp|amp\.html)/?$", "/", p.path).rstrip("/") or "/"
    keep = [(k, v) for k, v in parse_qsl(p.query) if not re.match(
        r"(utm_|fbclid|gclid|mc_|ref$|src$|source$|cmp$|cid$|ocid$|amp$|outputtype$|__twitter|_hs)", k, re.I)]
    if "news.google.com" in host:
        keep = []  # Google News links: the article id is in the path
    return urlunsplit(("https", host, path, urlencode(keep), ""))


# ------------------------------------------------------------------ the rules
SUBCLAUSE = re.compile(r"\b(as|amid|despite|after|due to|because|while|following)\b")


def category_scores(title):
    """Points per topic. Words in the main clause count fully; words after 'as', 'amid',
    'despite' etc. (usually the cause or background) count half. A phrase that sits
    inside a longer matched phrase isn't counted twice."""
    t = " %s " % title.lower()
    # Company names that contain topic words
    for name, plain in (("union pacific", "up railroad"), ("pilot flying j", "truck stop chain"),
                        ("freight hub", "terminal"), ("old dominion", "od freight")):
        t = t.replace(name, plain)
    m = SUBCLAUSE.search(t)
    main = t
    if m and len(t[:m.start()].split()) >= 3:
        main = t[:m.start()]
    scores = {}
    for cat, groups in CAT_WORDS.items():
        found = []
        for weight, ws in groups.items():
            for w in ws:
                if _has(t, [w]):
                    found.append((w.strip(), weight))
        pts = 0.0
        for w, weight in found:
            if any(w != o and w in o for o, _ in found):
                continue
            pts += weight * (1.0 if _has(main, [w]) else 0.5)
        scores[cat] = pts
    return scores


def assess(title, source="", snippet=""):
    """Decide whether one story belongs on HaulTimes.

    Returns dict: status ("ok" / "rejected" / "review"), reasons [..],
    category, importance (1-100), labels [..], kind.
    """
    raw = (title or "").strip()
    src = (source or "").strip()
    t = " %s " % raw.lower()
    full = " %s %s " % (raw.lower(), (snippet or "").lower())
    s = src.lower()
    reasons = []

    def reject(why):
        return {"status": "rejected", "reasons": [why], "category": "other", "importance": 0,
                "labels": [], "kind": "rejected"}

    if _has(t, MUSIC):
        return reject("music / entertainment")
    # 1. Broken or empty headlines, section pages, publisher-only titles
    words = re.findall(r"[A-Za-z0-9']+", raw)
    if not raw or MALFORMED.search(raw.strip()) or len(words) < 4 or norm_title(raw) == norm_title(src) \
            or (src and raw.lower().strip(" -|") == s.strip()):
        return reject("broken or publisher-only headline")
    # 2. Job ads
    if JOBS.search(raw):
        return reject("job listing / recruitment ad")
    # 3. Music, sports, lifestyle, consumer vehicles
    if _has(t, MUSIC):
        return reject("music / entertainment")
    if IDIOM.search(t) or (_has(t, FOOD_BANK) and "truckload" in t):
        return reject("'truckload' used as an expression, not freight news")
    if _has(t, CONSUMER) and not _has(t, ["fleet", "class 8", "commercial", "trucking", "semi"]):
        return reject("consumer vehicle / lifestyle story")
    if _has(t, LEGAL_MARKETING):
        return {"status": "review", "reasons": ["looks like law-firm marketing; check before showing"],
                "category": "regs", "importance": 30, "labels": [], "kind": "review"}
    # 4. Stock tips, market-research sales pages
    if _has(s, FINANCE_SOURCES) or STOCK.search(raw):
        return reject("stock commentary, no trucking development")
    if _has(s, RESEARCH_SOURCES) or RESEARCH.search(raw):
        return reject("market-research sales page")
    # 5. Other countries
    if _has(s, FOREIGN_SOURCES) and not _has(t, NA_PLACES):
        return reject("non-North American source")
    if ("£" in raw or "€" in raw or _has(t, UK_WORDS)) and not _has(t, ["u.s.", "canada", "canadian", "american", "usmca", "cusma"]):
        return reject("story about another country (UK/Europe)")
    t_geo = re.sub(r"new england|new south wales|new brunswick|new mexico|new york|new jersey", " na-place ", t)
    if _has(t_geo, FOREIGN) and not _has(t, ["u.s.", "canada", "canadian", "american", "usmca", "cusma", "tariff"]):
        return reject("story about another country")
    # 6. Ocean / air / rail freight with no North American trucking link
    if _has(t, OTHER_MODE) and not _has(t, NA_LINK):
        return reject("ocean/air freight with no North American trucking link")
    if ("freight rates" in t or "shipping rates" in t) and not is_trucking_source(src) \
            and not _has(t, ["truck", "trucking", "truckload", "ltl", "spot", "dat", "carrier"]):
        return reject("freight rates for another transport mode")

    # 7. Does it actually concern US/Canadian road freight?
    strong = _has(t, STRONG) or _has(t, CARRIERS) or _has(t, TRADE_NA) or _has(s, OFFICIAL_SOURCES)
    weak = sum(1 for w in WEAK if _has(t, [w]))
    trade_src = is_trucking_source(src)
    if not strong:
        if trade_src and weak >= 1:
            pass
        elif weak >= 2 and _has(t, ["truck", "freight", "diesel", "border", "logistics"]) \
                and not _has(t, CRIME_MINOR + ["plane", "train ", "car ", "bus "]):
            pass
        elif trade_src:
            reasons.append("trade-press story with no clear trucking keyword")
            return {"status": "review", "reasons": reasons, "category": "other", "importance": 30,
                    "labels": [], "kind": "review"}
        else:
            return reject("not about commercial trucking")

    # ------------------------------------------------------------ category
    scores = category_scores(raw)
    # A rail crossing is not a border crossing.
    if "rail crossing" in t or "railway crossing" in t or "level crossing" in t:
        scores["border"] -= 3
    best = max(CAT_ORDER, key=lambda c: (scores[c], -CAT_ORDER.index(c)))
    if scores[best] < 2:
        best = "other"

    # ------------------------------------------------------------ importance
    tier = source_tier(src)
    imp = 45
    for pts, ws in HIGH_IMPACT.items():
        if _has(t, ws):
            imp += pts
    imp += {1: 10, 2: 5, 3: 0, 4: -15}[tier]
    if _has(t, NATIONAL):
        imp += 5
    kind = "news"
    labels = []
    incident = _has(t, INCIDENT) and not _has(t, ["recall", "crash test", "crash data", "crash rate"])
    if incident and not _has(t, DISRUPTION):
        imp -= 25
        kind = "incident"
    elif incident:
        imp -= 5
        kind = "disruption"
    if _has(t, CRIME_MINOR):
        imp -= 20
        kind = "crime"
    if _has(t, HUMAN_INTEREST):
        imp -= 20
        kind = "feature"
    if _has(t, EVENT) and kind == "news":
        imp -= 10
        kind = "event"
    if _has(t, ROUNDUP):
        return {"status": "review", "reasons": ["weekly roundup of other outlets' stories; check before showing"],
                "category": "other", "importance": 30, "labels": [], "kind": "roundup"}
    if _has(s, WIRE_SOURCES) or "press release" in full:
        labels.append("Press release")
        imp -= 15
        kind = "press_release"
    elif ANNOUNCE.search(raw) and not _has(t, GOV) and kind == "news":
        labels.append("Company announcement")
        imp -= 10
        kind = "announcement"
    if _has(full, SPONSORED):
        labels.append("Sponsored")
        imp -= 25
        kind = "sponsored"
    if raw.endswith("?") and kind == "news":
        imp -= 5
    imp = max(1, min(99, imp))
    return {"status": SHOWN, "reasons": [], "category": best, "importance": imp, "labels": labels, "kind": kind}


# ------------------------------------------------------------------ overrides
def load_overrides():
    """overrides.json lets the site owner pin, hide or move a story.

    Stories are matched by id, by link, or by a piece of the headline.
    """
    try:
        with open(OVERRIDES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"pin": [], "exclude": [], "include": [], "category": {}, "importance": {}}
    for k in ("pin", "exclude", "include"):
        data[k] = [x for x in data.get(k, []) if isinstance(x, str) and x.strip() and not x.startswith("example")]
    for k in ("category", "importance"):
        data[k] = {a: b for a, b in (data.get(k) or {}).items() if not a.startswith("example")}
    return data


def _matches(story, key):
    key = key.strip()
    if not key:
        return False
    if key == story.get("id") or key == story.get("link"):
        return True
    if key.startswith("http"):
        return canonical_url(key) == canonical_url(story.get("link", ""))
    return len(key) >= 12 and key.lower() in (story.get("orig_title") or story.get("title", "")).lower()


def apply_overrides(story, ov):
    story.pop("pinned", None)
    for key in ov.get("include", []):
        if _matches(story, key):
            story["status"], story["reasons"] = SHOWN, ["shown by editor"]
    for key, cat in ov.get("category", {}).items():
        if _matches(story, key) and cat in CAT_WORDS:
            story["category"] = cat
            story.setdefault("reasons", []).append("topic set by editor")
    for key, val in ov.get("importance", {}).items():
        if _matches(story, key):
            try:
                story["importance"] = max(1, min(100, int(val)))
            except (TypeError, ValueError):
                pass
    for key in ov.get("pin", []):
        if _matches(story, key):
            story["pinned"] = True
            story["status"] = SHOWN
            story["importance"] = 100
    for key in ov.get("exclude", []):
        if _matches(story, key):
            story["status"], story["reasons"] = "rejected", ["hidden by editor"]
            story.pop("pinned", None)


# ------------------------------------------------------------------ duplicates
DEVELOPMENT = ["final", "approved", "approves", "signed", "signs", "passes", "passed", "ends", "ended", "delayed",
               "delays", "court", "ruling", "rules", "blocked", "reversed", "update", "now", "expands", "takes effect",
               "settles", "settlement", "files", "charged", "resumes", "reopens", "deal reached"]


def _when(s):
    try:
        return datetime.fromisoformat(s["published"])
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc)


def _strength(s):
    """Higher = better copy to keep: credible source, AI summary, earliest (the original)."""
    return (-source_tier(s.get("source")), bool(s.get("summary")), -_when(s).timestamp())


def mark_duplicates(stories):
    """Among shown stories, hide extra copies of the same article or event.

    Same link, same headline (syndicated copies), near-identical headlines,
    or several reports on one event (they share uncommon words and were
    published within two days). The best copy stays; a later report with a
    real new development stays too.
    """
    live = [s for s in stories if s.get("status") == SHOWN]
    for s in live:
        s.pop("dup_of", None)
    df = {}
    toks = {}
    for s in live:
        toks[s["id"]] = tokens(s.get("orig_title") or s["title"])
        for w in toks[s["id"]]:
            df[w] = df.get(w, 0) + 1
    rare_limit = max(3, len(live) // 40)

    order = sorted(live, key=_strength, reverse=True)
    kept = []
    for s in order:
        if s.get("pinned"):
            kept.append(s)
            continue
        a = toks[s["id"]]
        url = canonical_url(s.get("link"))
        nt = norm_title(s.get("orig_title") or s["title"])
        dup = None
        for k in kept:
            if abs((_when(s) - _when(k)).total_seconds()) > 3 * 86400:
                continue
            b = toks[k["id"]]
            if url and url == canonical_url(k.get("link")):
                dup = k
            elif nt and nt == norm_title(k.get("orig_title") or k["title"]):
                dup = k
            elif a and b:
                inter = a & b
                jacc = len(inter) / len(a | b)
                overlap = len(inter) / min(len(a), len(b))
                rare = [w for w in inter if df.get(w, 0) <= rare_limit and w not in GENERIC]
                close = abs((_when(s) - _when(k)).total_seconds()) <= 2 * 86400
                if jacc >= 0.6 or (overlap >= 0.75 and len(inter) >= 3):
                    dup = k
                elif close and len(inter) >= 3 and len(rare) >= 2 and overlap >= 0.3:
                    dup = k
            if dup:
                break
        if dup:
            later = _when(s) - _when(dup) > timedelta(hours=18)
            new_info = later and _has(" %s " % nt, [" %s " % w for w in DEVELOPMENT]) and \
                not _has(" %s " % norm_title(dup.get("orig_title") or dup["title"]), [" %s " % w for w in DEVELOPMENT])
            if new_info:
                s["followup_of"] = dup["id"]
                kept.append(s)
            else:
                s["status"], s["reasons"], s["dup_of"] = "duplicate", ["same story as: %s" % dup["title"][:90]], dup["id"]
        else:
            kept.append(s)


# ------------------------------------------------------------------ one call for everything
def reprocess(stories, now=None):
    """Re-check every stored story with the current rules. Never deletes anything."""
    now = now or datetime.now(timezone.utc)
    ov = load_overrides()
    for s in stories:
        s.setdefault("orig_title", s.get("title", ""))
        verdict = assess(s["orig_title"], s.get("source", ""), s.get("snippet", ""))
        ai = s.get("ai", True) is not False and s.get("summary")
        if verdict["status"] == SHOWN and ai and s.get("ai_category") in CAT_WORDS:
            # Trust Claude's topic and score when it wrote a summary, adjusted for source quality.
            verdict["category"] = s["ai_category"]
            tier = source_tier(s.get("source"))
            verdict["importance"] = max(1, min(99, int(s.get("ai_importance", 50)) + {1: 5, 2: 2, 3: 0, 4: -15}[tier]
                                               - (20 if verdict["kind"] in ("incident", "crime", "feature", "roundup", "sponsored") else 0)))
        if verdict["status"] == SHOWN and s.get("ai_relevant") is False:
            verdict["status"], verdict["reasons"] = "rejected", ["Claude judged it off-topic"]
        if verdict["status"] == SHOWN and not s.get("date_known", True):
            verdict["status"], verdict["reasons"] = "review", ["no publication date from the source"]
        s.update(status=verdict["status"], reasons=verdict["reasons"], category=verdict["category"],
                 importance=verdict["importance"], labels=verdict["labels"], kind=verdict["kind"])
        s.pop("followup_of", None)
        apply_overrides(s, ov)
    mark_duplicates(stories)
    return stories


def eligible(stories):
    """The one list every page uses: shown stories only, newest first."""
    out = [s for s in stories if s.get("status", SHOWN) == SHOWN and s.get("title")]
    out.sort(key=_when, reverse=True)
    return out


def lead_eligible(s):
    """Can this story be the big homepage headline?"""
    if s.get("pinned"):
        return True
    return (s.get("kind", "news") in ("news", "disruption")
            and source_tier(s.get("source")) <= 3
            and not s.get("title", "").endswith("?"))


def rank_score(s, now=None):
    """Editorial importance, gently reduced as the story ages (by its real publication time)."""
    now = now or datetime.now(timezone.utc)
    if s.get("pinned"):
        return 1000
    hours = max(0.0, (now - _when(s)).total_seconds() / 3600)
    return s.get("importance", 50) - min(40, hours * 0.6)
