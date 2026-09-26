"""Parsers for Google Jobs: job cards on a results page / next-page chunk and
the job viewer (/async/callback:8166). Verified 2026-09-24/26 against
captured pages (google_jobs/fixtures).

Where each field lives (a card and the viewer share the "viewer" markup —
the card carries it inside a <template>):

  card root  div.EimVGf[data-share-url]   title .PUpOsf, company .a3jPc,
             "Location • via Source" .FqK3wc, chips .ApHyTb .K3eUK
             (aria-label "Posted …" / "Employment Type …" / "Salary …" /
             "Qualification No degree mentioned"; the house icon = Work
             from home), the viewer token div[data-async-ons="8166"]
             [data-async-fc]
  viewer     [jsmodel] role=group [data-encoded-docid]: heading, logo
             .ZCPy9b img, header chips .fpMzBb .gm8wac (icon + text, no
             aria-label), apply buttons span.IjY5Tc, "Job highlights"
             h3 + h4 / ul li, "Job description" .OOyDTc + .ejCXj
  JS data    root jsdata ZSBYQe -> [[0, primary link, "jobs", id,
             description HTML, title, …, [[k, v] meta: organization,
             organization_mid, publisher_name, location_feature_id,
             cluster_id]]]; xQKg9c -> [.. , [[onet code, score, job zone]]];
             each apply span qqhBSc -> [link, domain, source, docid,
             is_direct, is_primary]; card root UmMWcb -> [.., primary
             link, .., "vt=20/docid=…", .., docid]
  viewer     employer section: h2 name, ratings a.SRK4ge (aria "…Glassdoor,
  only       Rated 4.3 out of 5,,29 reviews", /goto link), website a
             [title=<domain>] (/goto), "More jobs at …" /search link

Labels are localized with hl=, so chips are classified by their ICON
(two icon sets: cards and viewer), with text heuristics as the fallback.
"""
import html as htmllib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, parse_qsl, quote_plus, unquote, urlencode, urlparse, urlunparse

from lxml import html as lxml_html
from lxml.etree import ParserError

from google_jobs.markup import JsData, filter_links, is_chunk, jsdata_refs
from google_search.serp_parsers import first, text
from google_search.shared import clean_text, to_float

SITE = "https://www.google.com"
_UTF8 = lxml_html.HTMLParser(encoding="utf-8")

# chip icon (first 24 chars of the svg path) -> kind; cards and the viewer use
# different icon sets (2026-09-26). "salary_dollar" = the $ icon: the chip text
# then carries no currency sign ("101K–127K a year"), the icon is the "$".
_ICON_KINDS = {
    # cards
    "M11.99 2C6.47 2 2 6.48 2": "posted", "M20 6h-4V4c0-1.11-.89-2-": "job_type", "M19 1l-5 5v11l5-4.5z": "no_degree",
    "M11.8 10.9c-2.27-.59-3-1": "salary_dollar", "M2 5v14h20V5H2zm18 12H4V": "salary", "M10 20v-6h4v6h5v-8h3L12 ": "remote",
    # viewer
    "M612-292l56-56L520-496V-": "posted", "M160-120q-33,0-56.5-23.5": "job_type", "M480-160q-48-38-104-59T2": "no_degree",
    "M441-120v-86q-53-12-91.5": "salary_dollar", "M80-200V-760H880v560H80Z": "salary",
}
# viewer benefit chips: icon -> benefit key (the label is localized)
_BENEFIT_ICONS = {
    "M10.5,13H8v-3h2.5V7.5h3V": "health_insurance", "M15.05,20.07c-2.65-3.86-": "dental_insurance",
    "M19 4h-1V2h-2v2H8V2H6v2H": "paid_time_off", "M15,10c0-0.55,0.45-1,1-1": "retirement_plan",
}
_BENEFIT_WORDS = [("health_insurance", ("health insurance", "krankenversicherung")),
                  ("dental_insurance", ("dental",)), ("paid_time_off", ("paid time off", "urlaub", "pto")),
                  ("retirement_plan", ("retirement", "401", "altersvorsorge", "pension"))]
_ARIA_KINDS = {"posted": "posted", "employment": "job_type", "salary": "salary", "qualification": "no_degree"}

# ---- value parsing -----------------------------------------------------------------------------------

# pay period words, matched against whole words by prefix ("hr" must not hit "Jahr")
_PERIODS = {
    "hour": ("hour", "hr", "hourly", "stunde", "std", "heure", "hora", "ora", "uur", "godzin"),
    "day": ("day", "daily", "tag", "jour", "día", "dia", "giorno", "dag", "dzień"),
    "week": ("week", "woche", "semaine", "semana", "settimana"),
    "month": ("month", "monat", "mois", "mes", "mês", "mese", "maand", "miesi"),
    "year": ("year", "yr", "annum", "annual", "jahr", "année", "año", "ano", "anno", "jaar", "rok"),
}
_PERIOD_EXACT = {"an": "year", "j": "year"}      # fr "par an"; exact-match only
_CURRENCIES = [   # longest symbols first; "USA 87–USA 91 an hour" is how Google writes some US pay
    ("USA", "USD"), ("US$", "USD"), ("CA$", "CAD"), ("C$", "CAD"), ("AU$", "AUD"), ("A$", "AUD"), ("NZ$", "NZD"), ("HK$", "HKD"),
    ("S$", "SGD"), ("R$", "BRL"), ("MX$", "MXN"), ("CHF", "CHF"), ("AED", "AED"), ("SAR", "SAR"), ("RM", "MYR"),
    ("Rp", "IDR"), ("zł", "PLN"), ("Kč", "CZK"), ("£", "GBP"), ("€", "EUR"), ("₹", "INR"), ("¥", "JPY"),
    ("₩", "KRW"), ("₱", "PHP"), ("₦", "NGN"), ("₺", "TRY"), ("₫", "VND"), ("฿", "THB"), ("₪", "ILS"),
    ("kr", "SEK"), ("$", None),
]
_DOLLAR_COUNTRIES = {"US": "USD", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "SG": "SGD", "HK": "HKD", "MX": "MXN"}
_AMOUNT_RE = re.compile(r"(\d[\d.,   ]*\d|\d)\s*(k|m|l|lakh|lakhs|cr|tsd\.?|mil)?(?![a-z])", re.I)

_JOB_TYPES = [
    ("full_time", ("full-time", "full–time", "full time", "fulltime", "vollzeit", "temps plein", "tiempo completo",
                   "jornada completa", "tempo integral", "tempo pieno", "voltijd", "pełny etat")),
    ("part_time", ("part-time", "part–time", "part time", "teilzeit", "temps partiel", "tiempo parcial", "medio tiempo",
                   "meio período", "tempo parziale", "deeltijd")),
    ("contractor", ("contractor", "contract", "vertrag", "freiberuflich", "contrat", "contrato", "contratto")),
    ("internship", ("internship", "intern", "praktikum", "stage", "prácticas", "pasantía", "estágio", "tirocinio")),
    ("temporary", ("temporary", "befristet", "temporaire", "temporal", "temporário", "temporaneo")),
    ("per_diem", ("per diem",)),
    ("volunteer", ("volunteer", "ehrenamt", "bénévolat", "voluntariado")),
]
_TYPE_SPLIT_RE = re.compile(r"\s*(?:,|/|\band\b|\bund\b|\bet\b|\by\b|\be\b|\ben\b|\bo\b)\s*", re.I)

_AGE_UNITS = [
    ("minute", ("minute", "min", "minuto", "minuut")),
    ("hour", ("hour", "stunde", "heure", "hora", "ora", "uur", "godzin")),
    ("day", ("day", "tag", "jour", "día", "dia", "giorn", "dag", "dni", "dzień")),
    ("week", ("week", "woche", "semaine", "semana", "settiman", "tydz")),
    ("month", ("month", "monat", "mois", "mes", "mês", "mese", "maand", "miesi")),
]
_AGE_DELTA = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1), "day": timedelta(days=1),
              "week": timedelta(weeks=1), "month": timedelta(days=30)}


def _number(raw, suffix, decimal_comma):
    s = re.sub(r"[   ]", "", raw)
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if (len(tail) == 3 and not decimal_comma) or (len(tail) == 3 and s.count(",") > 1) \
            else head.replace(",", "") + "." + tail
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if len(tail) == 3 and not suffix and (decimal_comma or s.count(".") > 1):
            s = s.replace(".", "")
    try:
        value = float(s)
    except ValueError:
        return None
    mult = {"k": 1e3, "tsd": 1e3, "tsd.": 1e3, "m": 1e6, "mil": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5,
            "cr": 1e7}.get((suffix or "").lower(), 1)
    value *= mult
    return int(value) if value == int(value) else round(value, 2)


def parse_salary(value, country="US", language="en"):
    """'$101K–$127K a year' / '£600–£800 a day' / '54.000 € bis 93.000 €
    pro Jahr' -> {min, max, currency, period, text}; None when empty."""
    raw = clean_text(value)
    if not raw:
        return None
    low = raw.lower()
    currency = None
    for symbol, code in _CURRENCIES:
        if symbol.lower() in low if symbol.isalpha() else symbol in raw:
            currency = code or _DOLLAR_COUNTRIES.get((country or "US").upper(), "USD")
            break
    words = re.findall(r"[^\W\d_]+", low)
    period = next((key for word in words for key, stems in _PERIODS.items() if any(word.startswith(st) for st in stems)),
                  None) or next((_PERIOD_EXACT[w] for w in words if w in _PERIOD_EXACT), None)
    decimal_comma = (language or "en").split("-")[0].lower() not in ("en", "ja", "zh", "ko", "hi", "th", "he")
    amounts = [a for a in (_number(m.group(1), m.group(2), decimal_comma) for m in _AMOUNT_RE.finditer(raw)) if a is not None]
    return {
        "min": amounts[0] if amounts else None,
        "max": amounts[1] if len(amounts) > 1 else (amounts[0] if amounts else None),
        "currency": currency,
        "period": period,
        "text": raw,
    }


def parse_age(value, now=None):
    """'19 hours ago' / 'vor 2 Tagen' / '30+ days ago' -> 'YYYY-MM-DD' (UTC,
    the fetch time minus the age); None when not an age."""
    raw = (clean_text(value) or "").lower()
    if not raw:
        return None
    now = now or datetime.now(timezone.utc)
    if raw in ("just posted", "today", "heute", "aujourd'hui", "hoy", "hoje", "oggi", "vandaag"):
        return now.date().isoformat()
    m = re.search(r"(\d+)\+?\s*([^\d\s]+)", raw)
    if not m:
        return None
    unit = next((key for key, stems in _AGE_UNITS if any(m.group(2).startswith(s) for s in stems)), None)
    if not unit:
        return None
    return (now - int(m.group(1)) * _AGE_DELTA[unit]).date().isoformat()


def job_types(value):
    """'Full-time and Part-time' / 'Vollzeit und Teilzeit' -> ['full_time', 'part_time']."""
    raw = clean_text(value)
    if not raw:
        return []
    out = []
    for part in _TYPE_SPLIT_RE.split(raw):
        low = part.strip().lower()
        if not low:
            continue
        key = next((k for k, words in _JOB_TYPES if any(w == low or w in low for w in words)), None)
        key = key or re.sub(r"[^a-z0-9]+", "_", low).strip("_") or None
        if key and key not in out:
            out.append(key)
    return out


def strip_tracking(link):
    """Drop utm_* params Google adds to every apply link."""
    if not link:
        return None
    parts = urlparse(link)
    if not parts.query:
        return link
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunparse(parts._replace(query=urlencode(query)))


def description_text(html_text):
    """Job description HTML -> plain text with line breaks and bullets."""
    if not html_text:
        return None
    t = re.sub(r"(?i)<br\s*/?>", "\n", html_text)
    t = re.sub(r"(?i)<li[^>]*>", "\n• ", t)
    t = re.sub(r"(?i)</(p|div|li|ul|ol|h[1-6])>", "\n", t)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", t))
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in t.split("\n")]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or None


def job_link(job_id, query):
    """A Google link that opens the job: the results page for `query` with the
    job pinned first (htidocid) — also accepted by /details as `job`."""
    if not job_id:
        return None
    params = {"q": query or "jobs", "udm": 8, "htidocid": job_id}
    return f"{SITE}/search?{urlencode(params, quote_via=quote_plus)}"


def maps_link(feature_id):
    m = re.search(r"(0x[0-9a-f]+:0x[0-9a-f]+)", feature_id or "")
    return f"https://www.google.com/maps/place/?ftid={m.group(1)}" if m else None


def split_location(display, country=None):
    """'Chicago, IL' -> city Chicago, region IL; 'Bengaluru, Karnataka, India' ->
    city, region, country; one part (e.g. 'Anywhere', 'United States') -> none."""
    display = clean_text(display)
    core = re.sub(r"\s*\(\+\s*\d+[^)]*\)\s*$", "", display or "")    # "Chicago, IL (+4 others)"
    parts = [p.strip() for p in core.split(",") if p.strip()]
    city = region = country_name = None
    if len(parts) >= 3:
        city, region, country_name = parts[0], parts[1], parts[-1]
    elif len(parts) == 2:
        city = parts[0]
        if parts[1] in ("UK", "United Kingdom", "India", "Germany", "Deutschland", "France", "Canada", "Australia",
                        "Ireland", "Spain", "Italy", "Netherlands", "Singapore", "USA", "United States"):
            country_name = parts[1]
        else:
            region = parts[1]
    return {"display_name": display, "city": city, "region": region, "country": country_name}


# ---- documents -------------------------------------------------------------------------------------------

def parse_document(value):
    """A results page, chunk or viewer -> lxml tree (chunks carry no charset,
    so the parser is told UTF-8). None for a body without markup."""
    body = value or ""
    if is_chunk(body):
        start = body.find("<")
        body = body[start:] if start >= 0 else ""
    if "<" not in body:
        return None
    try:
        return lxml_html.fromstring(body.encode("utf-8", "replace"), parser=_UTF8)
    except (ParserError, ValueError):
        return None


def _icon(el):
    path = first(el, "svg path")
    return (path.get("d") or "")[:24] if path is not None else ""


def _chip_kind(el, label, value):
    if label:
        kind = _ARIA_KINDS.get(label.split(" ")[0].rstrip(":").lower())
        if kind:
            return kind
    icon = _icon(el)
    if icon in _BENEFIT_ICONS:
        return "benefit"
    kind = _ICON_KINDS.get(icon)
    if kind:
        return kind
    low = (value or "").lower()
    if parse_age(low):
        return "posted"
    if re.search(r"work from home|remote|homeoffice|télétravail|teletrabajo", low):
        return "remote"
    if "degree" in low or "abschluss" in low or "diplôme" in low:
        return "no_degree"
    if re.search(r"\d", low) and any(sym in value for sym, _ in _CURRENCIES):
        return "salary"
    if any(k in (t for t, _ in _JOB_TYPES) for k in job_types(value)):
        return "job_type"
    return "benefit"


def _benefit_key(el, value):
    icon_key = _BENEFIT_ICONS.get(_icon(el))
    if icon_key:
        return icon_key
    low = (value or "").lower()
    word_key = next((k for k, words in _BENEFIT_WORDS if any(w in low for w in words)), None)
    return word_key or (re.sub(r"[^a-z0-9]+", "_", low).strip("_") or None)


def _chips(els):
    """Card / viewer chips -> ({posted, job_type, salary, no_degree, remote}
    as text, [benefit keys])."""
    out, benefits = {}, []
    for el in els:
        labelled = first(el, "[aria-label]")
        label = (labelled.get("aria-label") if labelled is not None else None) or ""
        value = text(first(el, "span[aria-hidden='true'], .fLsjxc")) or text(el)
        kind = _chip_kind(el, label, value)
        if kind == "benefit":
            key = _benefit_key(el, value)
            if key and key not in benefits:
                benefits.append(key)
            continue
        if kind == "salary" and label:
            value = label.split(" ", 1)[1] if " " in label else value   # the aria text keeps the $ sign
        elif kind == "salary_dollar":
            kind, value = "salary", value if "$" in (value or "") else "$" + (value or "")
        out.setdefault(kind, value)
    return out, benefits


def _source_line(value):
    """'Chicago, IL • via LinkedIn' | 'Acme · Chicago, IL · via LinkedIn' -> (location, source)."""
    raw = clean_text(value) or ""
    via = re.search(r"(?:^|[•·])\s*(?:via|über|par|vía|via\s+de|tramite)\s+(.+)$", raw, re.I)
    source = via.group(1).strip() if via else None
    head = raw[:via.start()] if via else raw
    parts = [p.strip() for p in re.split(r"[•·]", head) if p.strip()]
    return parts, source


def _highlights(root):
    out = []
    for block in root.cssselect(".XFOJCe"):
        if first(block, "h3") is None:
            continue
        for h4 in block.cssselect("h4"):
            ul = h4.getnext()
            while ul is not None and ul.tag != "ul":
                ul = ul.getnext()
            items, more = [], 0
            for li in ul.cssselect("li") if ul is not None else []:
                value = text(li)
                if not value:
                    continue
                if "PsOuW" in (li.get("class") or ""):
                    more = int(re.search(r"\d+", value).group(0)) if re.search(r"\d+", value) else 0
                    continue
                items.append(value)
            out.append({"title": text(h4), "items": items, "more_count": more})
    return out


def _description_from_html(root):
    for block in root.cssselect(".XFOJCe"):
        head = first(block, "h2")
        spans = block.cssselect(".OOyDTc, .ejCXj")
        if head is not None and spans:
            parts = []
            for span in spans:
                raw = lxml_html.tostring(span, encoding="unicode")
                parts.append(raw)
            return description_text("".join(parts))
    return None


def _apply_options(root, js):
    """Apply buttons: any element whose jsdata points at an apply record
    (span.IjY5Tc in the English layout, span.aPSDzb in others)."""
    out, seen = [], set()
    for span in root.cssselect("[jsdata*='qqhBSc']"):
        data = js.ref(span, "qqhBSc")
        anchor = first(span, "a")
        title = anchor.get("title") if anchor is not None else None
        if isinstance(data, list) and data and isinstance(data[0], str):
            link = strip_tracking(data[0])
            if link in seen:
                continue
            seen.add(link)
            domain = (data[1] if len(data) > 1 and isinstance(data[1], str) else None) or \
                (urlparse(link).hostname or "").removeprefix("www.") or None
            out.append({
                "source": data[2] if len(data) > 2 and isinstance(data[2], str) else None,
                "domain": domain,
                "link": link,
                "is_direct": bool(data[4]) if len(data) > 4 and isinstance(data[4], int) else
                bool(title and "directly" in title.lower()),
            })
        elif anchor is not None and anchor.get("href"):
            source = re.sub(r"^Apply (?:directly )?on\s+", "", title or "", flags=re.I) or None
            out.append({"source": source, "domain": None, "link": SITE + anchor.get("href")
                        if anchor.get("href").startswith("/") else anchor.get("href"),
                        "is_direct": bool(title and "directly" in title.lower())})
    return out


def _meta(pairs):
    return {p[0]: p[1] for p in pairs if isinstance(p, list) and len(p) == 2 and isinstance(p[0], str)} \
        if isinstance(pairs, list) else {}


def _onet(value):
    try:
        code, _, zone = value[8][0][0], value[8][0][1], value[8][0][2]
    except (TypeError, IndexError):
        return None
    if not isinstance(code, int):
        return None
    s = str(code).zfill(8)
    return {"onet_code": f"{s[:2]}-{s[2:6]}.{s[6:]}", "onet_job_zone": zone if isinstance(zone, int) else None}


def _viewer_root(el):
    for node in el.cssselect("[data-encoded-docid][role='group']"):
        if jsdata_refs(node).get("ZSBYQe"):
            return node
    return None


def viewer(root, js, *, query=None, country="US", language="en", now=None):
    """The shared job fields from a viewer subtree (card <template> or
    /async/callback:8166 answer). Returns None when `root` has none."""
    vroot = _viewer_root(root)
    if vroot is None:
        return None
    data = js.ref(vroot, "ZSBYQe")
    main = data[0] if isinstance(data, list) and data and isinstance(data[0], list) else []
    meta = _meta(main[9] if len(main) > 9 else None)
    job_id = vroot.get("data-encoded-docid")
    title = (main[5] if len(main) > 5 and isinstance(main[5], str) else None) or vroot.get("data-title") \
        or text(first(vroot, "[role='heading']"))
    line_parts, source = _source_line(text(first(vroot, ".aW97bd")))
    company = meta.get("organization") or (line_parts[0] if line_parts else None)
    location = line_parts[1] if len(line_parts) > 1 else None
    chips, benefits = _chips(vroot.cssselect(".fpMzBb .gm8wac"))
    description_html = main[4] if len(main) > 4 and isinstance(main[4], str) else None
    options = _apply_options(vroot, js)
    logo = first(vroot, ".ZCPy9b img")
    return {
        "id": job_id,
        "title": clean_text(title),
        "company": company,
        "company_id": meta.get("organization_mid") or None,
        "logo": logo.get("src") if logo is not None and (logo.get("src") or "").startswith("http") else None,
        "location": location,
        "location_feature_id": meta.get("location_feature_id") or None,
        "source": meta.get("publisher_name") or source,
        "chips": chips,
        "benefits": benefits,
        "description": description_text(description_html) or _description_from_html(vroot),
        "description_html": description_html,
        "highlights": _highlights(vroot),
        "apply_options": options,
        "occupation": _onet(js.ref(vroot, "xQKg9c")),
    }


def assemble(fields, *, query, country="US", language="en", now=None, full=False):
    """Merged card / viewer fields -> the public job object."""
    chips = fields.get("chips") or {}
    options = fields.get("apply_options") or []
    loc = split_location(fields.get("location"), country)
    loc["google_maps_link"] = maps_link(fields.get("location_feature_id"))
    company_id = fields.get("company_id")
    out = {
        "id": fields.get("id"),
        "title": fields.get("title"),
        "link": job_link(fields.get("id"), query),
        "apply_link": options[0]["link"] if options else None,
        "is_remote": "remote" in chips or bool(re.search(r"\b(remote|anywhere)\b", (loc["display_name"] or "").lower())),
        "job_types": job_types(chips.get("job_type")),
        "salary": parse_salary(chips.get("salary"), country, language),
        "mentions_degree": False if "no_degree" in chips else None,
        "benefits": fields.get("benefits") or [],
        "date_posted": parse_age(chips.get("posted"), now),
        "posted_ago": clean_text(chips.get("posted")),
        "description": fields.get("description"),
    }
    if full:
        out["description_html"] = fields.get("description_html")
    out.update({
        "highlights": fields.get("highlights") or [],
        "company": {
            "name": fields.get("company"),
            "id": company_id,
            "logo": fields.get("logo"),
            "link": f"{SITE}/search?kgmid={company_id}" if company_id else None,
        },
        "location": loc,
        "source": fields.get("source"),
        "apply_options": options,
        "occupation": fields.get("occupation"),
    })
    return out


# ---- results page / chunk -------------------------------------------------------------------------------

def next_page_token(value):
    """The async token of the next 10 jobs (the infinite-scroll loader), or None."""
    m = re.search(r'<div[^>]*jsname="Yust4d"[^>]*data-async-fc="([^"]+)"', value or "") or \
        re.search(r'data-async-fc="([^"]+)"[^>]*data-async-ons="550"', value or "")
    return htmllib.unescape(m.group(1)) if m else None


def page_query(doc):
    el = first(doc, "[data-async-context]") if doc is not None else None
    m = re.match(r"query:(.*)", (el.get("data-async-context") if el is not None else "") or "")
    return unquote(m.group(1)) if m else None


def parse_results(value, *, query=None, country="US", language="en", now=None):
    """A results page or next-page chunk -> {query, jobs, detail_tokens,
    next_page_token}. `detail_tokens` maps job id -> the viewer token."""
    doc = parse_document(value)
    js = JsData(value)
    query = (page_query(doc) if doc is not None else None) or query
    jobs, tokens = [], {}
    for card in doc.cssselect("div.EimVGf[data-share-url]") if doc is not None else []:
        share = htmllib.unescape(card.get("data-share-url") or "")
        card_data = js.ref(card, "UmMWcb")
        job_id = (card_data[9] if isinstance(card_data, list) and len(card_data) > 9 else None) \
            or (parse_qs(urlparse(share).query).get("htidocid") or [None])[0]
        tmpl = first(card, "template")
        fields = viewer(tmpl if tmpl is not None else card, js, query=query, country=country, language=language) or {}
        line_parts, source = _source_line(text(first(card, ".FqK3wc")))
        card_chips, _ = _chips(card.cssselect(".ApHyTb .K3eUK"))
        fav = next((v for v in (js.ref(el, "rj9Cic") for el in card.cssselect("[jsdata*='dt_fav_jobs']")) if v), None)
        fav_logo = fav[6][0] if isinstance(fav, list) and len(fav) > 6 and isinstance(fav[6], list) and fav[6] else None
        fields.update({
            "id": job_id or fields.get("id"),
            "title": fields.get("title") or text(first(card, ".PUpOsf")),
            "company": fields.get("company") or text(first(card, ".a3jPc")),
            "location": (line_parts[0] if line_parts else None) or fields.get("location"),
            "source": fields.get("source") or source,
            "chips": {**(fields.get("chips") or {}), **card_chips},
            "logo": fields.get("logo") or (fav_logo if isinstance(fav_logo, str) else None),
        })
        job = assemble(fields, query=query, country=country, language=language, now=now)
        job = {"position": len(jobs) + 1, **job}
        jobs.append(job)
        token_el = first(card, "[data-async-ons='8166'][data-async-fc]")
        if job["id"] and token_el is not None:
            tokens[job["id"]] = token_el.get("data-async-fc")
    return {"query": query, "jobs": jobs, "detail_tokens": tokens, "next_page_token": next_page_token(value)}


# ---- viewer (job details) --------------------------------------------------------------------------------

def _rating(anchor):
    label = anchor.get("aria-label") or ""
    source = text(first(anchor, ".Z33Opb"))
    score = to_float(text(first(anchor, ".kgGzCe")))
    count_text = text(first(anchor, ".fuyCVc span"))
    return {
        "source": source,
        "rating": score,
        "review_count": _count(count_text),
        "link": _outbound(anchor.get("href")),
    } if source or label else None


def _outbound(href):
    """An employer / ratings href: a /goto wrapper made absolute (jobs.py
    resolves it), or a direct link with Google's utm_* dropped — the viewer
    serves either form (2026-09-26)."""
    if not href:
        return None
    if href.startswith("/"):
        return SITE + href
    return href if "/goto?" in href else strip_tracking(href)


def _count(value):
    """'70.6K' -> 70600, '1.2M' -> 1200000, '29' -> 29."""
    m = re.match(r"^\s*([\d.,]+)\s*([KkMm]?)", value or "")
    if not m:
        return None
    num = float(m.group(1).replace(",", "")) if m.group(2) else float(re.sub(r"[.,]", "", m.group(1)))
    return int(round(num * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1)))


def parse_details(value, *, query=None, country="US", language="en", now=None):
    """/async/callback:8166 answer -> the full job object (viewer fields +
    employer website and ratings); None when the answer holds no job."""
    doc = parse_document(value)
    if doc is None:
        return None
    js = JsData(value)
    fields = viewer(doc, js, query=query, country=country, language=language)
    if not fields or not fields.get("id"):
        return None
    job = assemble(fields, query=query, country=country, language=language, now=now, full=True)
    ratings = [r for r in (_rating(a) for a in doc.cssselect("a.SRK4ge")) if r]
    website = None
    for a in doc.cssselect("a[title][href]"):
        title = a.get("title") or ""
        href = a.get("href") or ""
        if re.fullmatch(r"[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}", title, re.I) and ("/goto?" in href or href.startswith("http")):
            website = {"domain": title, "link": _outbound(href)}
            break
    job["company"].update({
        "website": website["link"] if website else None,
        "domain": website["domain"] if website else None,
        "ratings": ratings,
    })
    return job


# ---- filters ------------------------------------------------------------------------------------------------

def filter_suffixes(value, base_query):
    """The localized filter wording a results page offers, by position:
    {"date_posted": [yesterday, 3 days, week, month], "job_type": [full time,
    part time, contract, internship]} as the words Google appends to the
    query (e.g. "in the last week", "Vollzeit"), plus "remote" / "no_degree"
    toggles from the chip bar."""
    groups, current = [], []
    base = (base_query or "").strip().lower()
    for label, link in filter_links(value):
        q = (parse_qs(urlparse(link).query).get("q") or [""])[0].strip()
        if not q or q.lower() == base:        # the group's own entry (no q, or the unfiltered query) closes it
            groups.append(current)
            current = []
        elif q.lower().startswith(base):
            current.append(q[len(base):].strip())
    out = {}
    for group in groups:
        if len(group) == 4:
            kind = "date_posted" if re.search(r"\d", group[1]) else "job_type"
            out.setdefault(kind, group)
    doc = parse_document(value)
    for a in doc.cssselect("[role='listitem'] a[href*='uds=']") if doc is not None else []:
        q = (parse_qs(urlparse(htmllib.unescape(a.get("href"))).query).get("q") or [""])[0].strip()
        if not q.lower().startswith(base):
            continue
        suffix = q[len(base):].strip()
        icon = _icon(a)
        kind = "remote" if icon == _ICON_KEY_REMOTE or re.search(r"remote|homeoffice|télétravail|remoto", suffix, re.I) \
            else "no_degree" if re.search(r"degree|abschluss|diplôme|título", suffix, re.I) else None
        if kind:
            out.setdefault(kind, suffix)
    return out


_ICON_KEY_REMOTE = "M10 20v-6h4v6h5v-8h3L12 "
