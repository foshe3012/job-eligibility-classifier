#!/usr/bin/env python3
"""
Job eligibility pipeline — stage 1.

Pulls full job boards from public ATS endpoints (no auth, no scraping),
normalises them, and scores each COMPANY on how plausibly it can employ
someone in a given country — based on its whole hiring footprint, not
a single listing's "remote" flag.

Run:  python3 job_eligibility.py
Out:  jobs.json  (normalised listings + eligibility tiers)
      companies.json (company-level footprint scores)

stdlib only. No pip install.
"""

import json, re, sys, urllib.request, urllib.error
from collections import defaultdict
from datetime import datetime, timezone

# ---------------------------------------------------------------- companies
# slug = the identifier in the ATS URL.
#
# VERIFIED list: (source, slug) pairs confirmed to return jobs.
# Run `python3 job_eligibility.py --probe` first to build this list — it tries
# every candidate below against all three ATSes and prints what actually works.
COMPANIES = [
    ("ashby",      "abridge"),           # 43
    ("ashby",      "amplitude"),         # 36
    ("ashby",      "andela"),            # 15
    ("ashby",      "attio"),             # 37
    ("ashby",      "buffer"),            # 1
    ("ashby",      "clickup"),           # 52
    ("ashby",      "close"),             # 7
    ("ashby",      "cohere"),            # 137
    ("ashby",      "cursor"),            # 132
    ("ashby",      "decagon"),           # 147
    ("ashby",      "docker"),            # 60
    ("ashby",      "elevenlabs"),        # 177
    ("ashby",      "harvey"),            # 299
    ("ashby",      "linear"),            # 30
    ("ashby",      "mercor"),            # 114
    ("ashby",      "miro"),              # 25
    ("ashby",      "notion"),            # 128
    ("ashby",      "openai"),            # 832
    ("ashby",      "oyster"),            # 25
    ("ashby",      "plaid"),             # 123
    ("ashby",      "railway"),           # 8
    ("ashby",      "ramp"),              # 156
    ("ashby",      "render"),            # 40
    ("ashby",      "replit"),            # 73
    ("ashby",      "sentry"),            # 41
    ("ashby",      "sierra"),            # 202
    ("ashby",      "supabase"),          # 49
    ("ashby",      "vanta"),             # 86
    ("ashby",      "zapier"),            # 11
    ("greenhouse", "airtable"),          # 4
    ("greenhouse", "anthropic"),         # 636
    ("greenhouse", "brex"),              # 263
    ("greenhouse", "canonical"),         # 306
    ("greenhouse", "chime"),             # 64
    ("greenhouse", "coinbase"),          # 213
    ("greenhouse", "figma"),             # 163
    ("greenhouse", "gitlab"),            # 200
    ("greenhouse", "grafanalabs"),       # 123
    ("greenhouse", "mercury"),           # 63
    ("greenhouse", "mixpanel"),          # 73
    ("greenhouse", "netlify"),           # 4
    ("greenhouse", "remotecom"),         # 66
    ("greenhouse", "scaleai"),           # 192
    ("greenhouse", "stripe"),            # 715
    ("greenhouse", "turing"),            # 29
    ("greenhouse", "vercel"),            # 91
    ("greenhouse", "webflow"),           # 27
    ("greenhouse", "wise"),              # 16
    ("lever",      "toptal"),            # 33
]

# Candidate slugs for --probe. ATS unknown; the probe figures it out.
# Skewed toward AI + remote-first companies, which is the launch niche.
PROBE_CANDIDATES = [
    # AI / ML
    "elevenlabs", "mercor", "anthropic", "openai", "perplexityai", "perplexity",
    "scaleai", "scale-ai", "huggingface", "cohere", "runwayml", "together",
    "harvey", "sierra", "decagon", "abridge", "cursor", "anysphere",
    # dev tools / infra
    "linear", "vercel", "netlify", "supabase", "railway", "render", "gitlab",
    "sentry", "postman", "grafanalabs", "hashicorp", "docker", "replit",
    # fintech / payments
    "stripe", "ramp", "mercury", "wise", "brex", "plaid", "chime", "coinbase",
    # remote-first / global-employment (highest prior for Nigeria eligibility)
    "deel", "remotecom", "oyster", "papayaglobal", "andela", "turing",
    "toptal", "crossover", "automattic", "gitlab", "zapier", "doist",
    "buffer", "canonical", "sourcegraph", "close", "hotjar", "invision",
    # product / SaaS
    "notion", "figma", "airtable", "loom", "miro", "webflow", "clickup",
    "vanta", "clay", "attio", "retool", "amplitude", "mixpanel",
]

TARGET_COUNTRY = "nigeria"        # the candidate's country
UA = {"User-Agent": "eligibility-research/0.1"}

# ------------------------------------------------------------------ helpers
GLOBAL_SOUTH = {
    "nigeria","kenya","ghana","south africa","egypt","morocco","india","pakistan",
    "bangladesh","philippines","indonesia","vietnam","brazil","argentina","colombia",
    "mexico","chile","peru","ukraine","poland","romania","serbia","turkey","kenya",
}
COUNTRY_HINTS = {
    "united states":"united states","usa":"united states","u.s.":"united states",
    "san francisco":"united states","new york":"united states","seattle":"united states",
    "austin":"united states","boston":"united states","washington":"united states",
    "united kingdom":"united kingdom","uk":"united kingdom","london":"united kingdom",
    "canada":"canada","toronto":"canada","vancouver":"canada",
    "germany":"germany","berlin":"germany","france":"france","paris":"france",
    "spain":"spain","madrid":"spain","barcelona":"spain","netherlands":"netherlands",
    "amsterdam":"netherlands","poland":"poland","warsaw":"poland","ireland":"ireland",
    "dublin":"ireland","india":"india","bangalore":"india","singapore":"singapore",
    "japan":"japan","tokyo":"japan","korea":"korea","australia":"australia",
    "brazil":"brazil","mexico":"mexico","argentina":"argentina","nigeria":"nigeria",
    "kenya":"kenya","uae":"uae","dubai":"uae","sweden":"sweden","italy":"italy",
    "belgium":"belgium","portugal":"portugal","israel":"israel","lithuania":"lithuania",
    # v2 additions — every one of these was missed on the labelled sample
    "us":"united states","u.s":"united states","foster city":"united states",
    "palo alto":"united states","mountain view":"united states",
    "los angeles":"united states","chicago":"united states","denver":"united states",
    "atlanta":"united states","miami":"united states","dallas":"united states",
    "ksa":"saudi arabia","saudi":"saudi arabia","saudi arabia":"saudi arabia",
    "riyadh":"saudi arabia","abu dhabi":"uae","doha":"qatar","qatar":"qatar",
    "zurich":"switzerland","switzerland":"switzerland","munich":"germany",
    "stockholm":"sweden","copenhagen":"denmark","denmark":"denmark",
    "oslo":"norway","norway":"norway","helsinki":"finland","finland":"finland",
    "lisbon":"portugal","milan":"italy","rome":"italy","vienna":"austria",
    "austria":"austria","prague":"czechia","czechia":"czechia",
    "bengaluru":"india","mumbai":"india","delhi":"india","hyderabad":"india",
    "seoul":"korea","taipei":"taiwan","taiwan":"taiwan","hong kong":"hong kong",
    "sydney":"australia","melbourne":"australia","auckland":"new zealand",
    "new zealand":"new zealand","sao paulo":"brazil","são paulo":"brazil",
    "bogota":"colombia","colombia":"colombia","lima":"peru",
    "buenos aires":"argentina","mexico city":"mexico","santiago":"chile",
    "lagos":"nigeria","abuja":"nigeria","nairobi":"kenya","accra":"ghana",
    "cape town":"south africa","johannesburg":"south africa",
    "cairo":"egypt","egypt":"egypt","casablanca":"morocco",
    "manila":"philippines","jakarta":"indonesia","bangkok":"thailand",
    "thailand":"thailand","kuala lumpur":"malaysia","malaysia":"malaysia",
    "bucharest":"romania","romania":"romania","belgrade":"serbia",
    "istanbul":"turkey","kyiv":"ukraine","ukraine":"ukraine",
    "tel aviv":"israel","vilnius":"lithuania","tallinn":"estonia",
    "estonia":"estonia","montreal":"canada","ottawa":"canada",
    "edinburgh":"united kingdom","manchester":"united kingdom",
    "dublin, ireland":"ireland","brussels":"belgium","geneva":"switzerland",
}
# v2. "globally" and "fully global" were REMOVED. They matched boilerplate in
# job descriptions ("we serve customers globally", "growing our team globally")
# and turned San Francisco-only roles into confirmed_global. Validated against
# 28 hand-labelled postings on 2026-10-01: open precision was 0.0% because of
# this. WORLDWIDE is now matched against LOCATION FIELDS ONLY, never prose.
WORLDWIDE = re.compile(
    r"\b(worldwide|anywhere in the world|any country|work from anywhere|"
    r"global(?:ly)? remote|remote - global|fully remote - worldwide)\b", re.I)

# STRONG: a claim about where the EMPLOYEE MAY LIVE. Outranks a city in the
# location field, because an office address is not a residency requirement.
DESC_OPENS_STRONG = re.compile(
    r"(work from anywhere(?: in the world)?|"
    r"hire(?: people)?(?: in| from)? any(?:where| country)|"
    r"no location requirement|location[- ]independent|"
    r"you (?:can|may) (?:live|work|be based) anywhere|"
    r"we (?:are|'re) (?:a )?fully (?:distributed|remote) company|"
    r"employ(?:ees)? in over \d+ countries|"
    r"we can (?:employ|hire|pay) (?:people )?in (?:any country|\d+\+? countries))",
    re.I)

# WEAK: sounds permissive, commits to nothing. This is the same trap as the
# word "globally" — it is about who may APPLY, not who they can PAY. Never
# treat as eligibility; only ever used to downgrade a hard 'restricted'.
DESC_OPENS_WEAK = re.compile(
    r"(applicants? from (?:all|any) (?:countries|backgrounds)|"
    r"we welcome applications from|encourage (?:applications|candidates) from|"
    r"equal opportunit|regardless of .{0,40}national origin|"
    r"diverse (?:candidates|applicants|backgrounds))", re.I)

# RELOCATION is NOT remote eligibility. The job is in a city; they will help
# you move there, which for a Nigeria-based candidate means visa sponsorship.
# Tracked as its own tier so it can be surfaced separately, never blended in.
DESC_RELOCATION = re.compile(
    r"(relocation (?:assistance|support|package|benefits?|allowance)|"
    r"(?:we|will) (?:offer|provide|assist with|cover) relocation|"
    r"willing to relocate|visa sponsorship (?:is )?(?:available|provided|offered)|"
    r"we sponsor (?:work )?visas?)", re.I)

# phrases that signal a hard restriction, checked against description text
RESTRICTION_PATTERNS = [
    (re.compile(r"must (be|reside|live) (located |based )?in ([A-Z][\w\s,]+)", re.I), "must_be_located_in"),
    (re.compile(r"(authori[sz]ed|eligible) to work in ([A-Z][\w\s,]+)", re.I),        "work_authorisation"),
    (re.compile(r"\bno (visa )?sponsorship\b", re.I),                                  "no_sponsorship"),
    (re.compile(r"\bresidents? of ([A-Z][\w\s,]+) only\b", re.I),                      "residents_only"),
    (re.compile(r"open to candidates (based |located )?in ([A-Z][\w\s,]+)", re.I),     "candidate_location_list"),
    (re.compile(r"within \d+ (hours|time zones) of", re.I),                            "timezone_band"),
    (re.compile(r"\b(this role is|role is) based (remotely )?in ([A-Z][\w\s,]+)", re.I),"role_based_in"),
]


def fetch(url, quiet=False):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError,
            json.JSONDecodeError, TimeoutError) as e:
        if not quiet:
            print(f"  ! {url} -> {e}")
        return None


def to_country(text):
    """Best-effort location string -> country. Deliberately conservative."""
    if not text:
        return None
    t = text.lower()
    if WORLDWIDE.search(t):
        return "worldwide"
    if US_STATE_ABBR.search(text):          # case-sensitive: "City, CA"
        return "united states"
    # longest hint first, so "south africa" wins over "africa"-style overlaps
    for hint in sorted(COUNTRY_HINTS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(hint)}\b", t):
            return COUNTRY_HINTS[hint]
    return None


def strip_html(s):
    return re.sub(r"<[^>]+>", " ", s or "")


# ----------------------------------------------------------------- adapters
def from_ashby(slug):
    d = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        locs = [j.get("location")] + (j.get("secondaryLocations") or [])
        out.append(dict(
            source="ashby", company=slug, job_id=j.get("id"), title=j.get("title","").strip(),
            department=j.get("department"), employment_type=j.get("employmentType"),
            locations=[l for l in locs if isinstance(l, str)],
            is_remote=bool(j.get("isRemote")), published_at=j.get("publishedAt"),
            url=j.get("jobUrl"), apply_url=j.get("applyUrl"),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
        ))
    return out


def from_greenhouse(slug):
    d = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        out.append(dict(
            source="greenhouse", company=slug, job_id=j.get("id"), title=(j.get("title") or "").strip(),
            department=(j.get("departments") or [{}])[0].get("name"),
            employment_type=None, locations=[loc] if loc else [],
            is_remote=bool(loc and "remote" in loc.lower()),
            published_at=j.get("updated_at"), url=j.get("absolute_url"), apply_url=j.get("absolute_url"),
            description=strip_html(j.get("content")),
        ))
    return out


def from_lever(slug):
    d = fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(d, list):
        return []
    out = []
    for j in d:
        c = j.get("categories") or {}
        loc = c.get("location")
        out.append(dict(
            source="lever", company=slug, job_id=j.get("id"), title=(j.get("text") or "").strip(),
            department=c.get("department"), employment_type=c.get("commitment"),
            locations=[loc] if loc else [],
            is_remote=bool(loc and "remote" in loc.lower()),
            published_at=j.get("createdAt"), url=j.get("hostedUrl"), apply_url=j.get("applyUrl"),
            description=j.get("descriptionPlain") or strip_html(j.get("description")),
        ))
    return out


ADAPTERS = {"ashby": from_ashby, "greenhouse": from_greenhouse, "lever": from_lever}

PROBE_URLS = {
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{s}",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true",
    "lever":      "https://api.lever.co/v0/postings/{s}?mode=json",
}


def probe():
    """Find which ATS (if any) each candidate slug lives on.

    Costs one request per (slug, ats) miss, so it's slow but it runs once.
    Prints a COMPANIES block you can paste straight back into this file.
    """
    hits, misses = [], []
    seen = set()
    for slug in PROBE_CANDIDATES:
        if slug in seen:
            continue
        seen.add(slug)
        found = None
        for source, tmpl in PROBE_URLS.items():
            d = fetch(tmpl.format(s=slug), quiet=True)
            if d is None:
                continue
            n = len(d) if isinstance(d, list) else len(d.get("jobs", []))
            if n:
                found = (source, n)
                break
        if found:
            hits.append((slug, found[0], found[1]))
            print(f"  ✓ {slug:16} {found[0]:11} {found[1]:4} jobs")
        else:
            misses.append(slug)
            print(f"  · {slug:16} not found on any ATS")

    print(f"\n{len(hits)} of {len(seen)} slugs resolved.\n")
    print("Paste this over the COMPANIES list in this file:\n")
    print("COMPANIES = [")
    for slug, source, n in sorted(hits, key=lambda h: (h[1], h[0])):
        print(f'    ("{source}",{" " * (11 - len(source))}"{slug}"),'
              f'{" " * max(1, 18 - len(slug))}# {n} jobs')
    print("]")
    if misses:
        print(f"\n# not found (wrong slug, or a different ATS): {', '.join(misses)}")


# --------------------------------------------------------- company footprint
def score_company(jobs):
    """The differentiating signal: can this employer pay someone abroad at all?"""
    countries = set()
    for j in jobs:
        for l in j["locations"]:
            c = to_country(l)
            if c:
                countries.add(c)
    countries.discard(None)
    gs = countries & GLOBAL_SOUTH
    n = len(countries - {"worldwide"})

    if "worldwide" in countries:
        tier = "global"
    elif n >= 5 and gs:
        tier = "global"          # proven payroll reach incl. emerging markets
    elif n >= 5:
        tier = "multi_region"
    elif n >= 3:
        tier = "multi_country"
    elif n <= 2 and countries:
        tier = "single_region"
    else:
        tier = "unknown"

    return dict(
        tier=tier, country_count=n, countries=sorted(countries),
        global_south_countries=sorted(gs),
        hires_in_target=TARGET_COUNTRY in countries,
        job_count=len(jobs),
    )


# ------------------------------------------------------------ job eligibility
def job_signals(job):
    sig = []
    desc = job.get("description") or ""
    for pat, name in RESTRICTION_PATTERNS:
        if pat.search(desc):
            sig.append(name)
    return sig


# v2. The old single REGION_LOCKS pattern treated EMEA and Africa as locks.
# Nigeria is IN both. That scored 0/2 precision on the hand-labelled sample
# (Canonical "Home based - EMEA" and Oyster "EMEA" were both wrongly excluded).
# Regions now split by whether they CONTAIN the target country.
REGION_INCLUDES_TARGET = re.compile(
    r"\b(emea|mea|africa|middle east(?: and africa)?|sub[- ]saharan|"
    r"west africa|global south|eu[- ]?emea)\b", re.I)

REGION_EXCLUDES_TARGET = re.compile(
    r"\b(amer|namer|nasa|north america|latam|latin america|south america|"
    r"americas|apac|apj|aipac|anz|australia/new zealand|"
    r"europe(?!, middle east)|eu only|us only|uk only|dach|benelux|nordics|"
    r"iberia|asia pacific|southeast asia|united states only|canada only|"
    r"na region|emea excluded)\b", re.I)
# 'amer' added 2026-10-01: five sampled Supabase postings were tagged
# "Remote, AMER" and the token matched nothing, so the region was invisible.

# US state abbreviations seen in "City, ST" location strings — these were
# silently unrecognised, so "Foster City, CA" yielded no country at all.
US_STATE_ABBR = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|"
    r"MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|"
    r"VA|WA|WV|WI|WY|DC)\b")


def eligibility(job, comp):
    """Three tiers. Deliberately not a binary 'verified' claim."""
    sig = job_signals(job)
    locs = " ".join(job["locations"])
    desc = job.get("description") or ""

    strong = bool(DESC_OPENS_STRONG.search(desc))
    reloc = bool(DESC_RELOCATION.search(desc))

    # 1. Worldwide in the LOCATION field. Prose is too noisy — see the note on
    #    WORLDWIDE above. A hard restriction phrase still overrides it.
    if WORLDWIDE.search(locs):
        if sig:
            return "unclear", sig + ["worldwide_but_restriction_text"]
        return "confirmed_global", sig

    # 2. An explicit residency statement in the body outranks the location
    #    field: an office address is not a residency requirement. This is the
    #    precedence fix from 2026-10-01 — previously a named city returned
    #    'restricted' here and the body text was never read.
    if strong:
        # A work-from-anywhere claim that sits alongside a region tag excluding
        # the target, or a hard restriction phrase, is a CONTRADICTION. Audited
        # 2026-10-01: five Supabase postings said work-from-anywhere while
        # tagged "Remote, AMER". Those belong in unclear for a human to settle,
        # not in the tier the product calls confirmed.
        if REGION_EXCLUDES_TARGET.search(locs):
            return "unclear", sig + ["work_from_anywhere_vs_region_tag"]
        if sig:
            return "unclear", sig + ["work_from_anywhere_contradicted_by_restriction"]
        return "confirmed_global", sig + ["description_states_work_from_anywhere"]

    # 3. A named city or country in the location field settles it, and outranks
    #    both the company footprint and the isRemote flag.
    job_countries = {c for c in (to_country(l) for l in job["locations"])
                     if c and c != "worldwide"}
    if job_countries:
        if TARGET_COUNTRY in job_countries:
            return "confirmed_global", sig
        # Onsite role offering relocation / sponsorship is its own category.
        # NOT remote-eligible: it requires moving and a visa.
        if reloc:
            return "relocation_only", sig + ["relocation_or_sponsorship_offered"]
        return "restricted", sig + ["job_location_country_mismatch"]

    # 4. Region names, split by whether the target country sits inside them.
    if REGION_EXCLUDES_TARGET.search(locs):
        return "restricted", sig + ["region_excludes_target"]
    if REGION_INCLUDES_TARGET.search(locs):
        if sig:
            return "unclear", sig + ["region_includes_target_with_caveat"]
        return "likely_eligible", sig + ["region_includes_target"]

    # 5. Explicit restriction text in the body.
    if sig:
        return "restricted", sig

    # 6. Nothing in the posting. Fall back to employer footprint — and this is
    #    now capped at "likely" or "unclear". It never returns confirmed:
    #    a footprint is evidence about the employer, not about this job.
    if comp["hires_in_target"]:
        return "likely_eligible", sig + ["employer_hires_in_target"]
    if job["is_remote"] and comp["tier"] == "global":
        return "unclear", sig + ["remote_global_employer_no_country_stated"]
    if job["is_remote"]:
        return "unclear", sig + ["remote_no_country_stated"]
    return "restricted", sig or ["onsite_or_unstated"]


# --------------------------------------------------------------- de-duplication
def collapse(jobs):
    """Ashby (and sometimes Greenhouse) emit one row per job x location.

    A role open in 18 countries therefore appears 18 times, and 17 of those
    rows look 'restricted' for any single target country even though the JOB
    is open. Grouping by (company, title) and unioning locations gives the
    real unit of analysis: one opening.
    """
    groups = {}
    for j in jobs:
        key = (j["company"], re.sub(r"\s+", " ", j["title"].lower()).strip())
        g = groups.setdefault(key, dict(
            company=j["company"], source=j["source"], title=j["title"],
            locations=[], is_remote=False, description="", rows=0,
            urls=[], department=j.get("department"),
        ))
        g["rows"] += 1
        for l in j["locations"]:
            if l not in g["locations"]:
                g["locations"].append(l)
        g["is_remote"] = g["is_remote"] or j["is_remote"]
        if len(j.get("description") or "") > len(g["description"]):
            g["description"] = j["description"]
        if j.get("url") and j["url"] not in g["urls"]:
            g["urls"].append(j["url"])
    return list(groups.values())


def tally(items, label, width=58):
    # v3 fix: 'reasons' previously counted signals on EVERY job, so eligibility
    # signals (region_includes_target, description_states_work_from_anywhere)
    # showed up in a list headed "why restricted". Now split by verdict.
    counts = defaultdict(int)
    reasons, elig_signals = defaultdict(int), defaultdict(int)
    remote_flagged = 0
    for j in items:
        counts[j["eligibility"]] += 1
        if j["eligibility"] == "restricted":
            for s in j["restriction_signals"]:
                reasons[s] += 1
        else:
            for s in j["restriction_signals"]:
                elig_signals[s] += 1
        if j["is_remote"]:
            remote_flagged += 1
    n = len(items) or 1

    print(f"\n{'='*width}\n{label}  ({len(items)})\n{'='*width}")
    for k in ("confirmed_global", "likely_eligible", "unclear",
              "relocation_only", "restricted"):
        print(f"  {k:18} {counts[k]:5}   {counts[k]/n*100:5.1f}%")

    open_to = counts["confirmed_global"] + counts["likely_eligible"]
    print(f"\n  open to {TARGET_COUNTRY:11} {open_to:5}   {open_to/n*100:5.1f}%")
    print(f"  NOT open            {counts['restricted']:5}"
          f"   {counts['restricted']/n*100:5.1f}%   <- the wedge")

    false_remote = sum(1 for j in items
                       if j["is_remote"] and j["eligibility"] == "restricted")
    print(f"\n  tagged 'remote'     {remote_flagged:5}")
    print(f"  ...but restricted   {false_remote:5}"
          f"   {false_remote/max(remote_flagged,1)*100:5.1f}% of remote")

    if reasons:
        print("\n  why restricted (restricted jobs only):")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {r:40} {c:5}")
    conc = defaultdict(set)
    for j in items:
        conc[j["eligibility"]].add(j.get("company"))
    print("\n  distinct companies per tier (a tier carried by 1-2 employers")
    print("  is an employer quirk, not a general rule):")
    for k in ("confirmed_global", "likely_eligible", "unclear",
              "relocation_only", "restricted"):
        if counts[k]:
            print(f"    {k:22} {counts[k]:5} jobs across "
                  f"{len(conc[k]):3} companies")

    if elig_signals:
        print("\n  signals on NON-restricted jobs:")
        for r, c in sorted(elig_signals.items(), key=lambda x: -x[1]):
            print(f"    {r:40} {c:5}")
    return counts


# ------------------------------------------------------------------- runner
def main():
    all_jobs, company_rows = [], {}
    for source, slug in COMPANIES:
        print(f"→ {source}:{slug}")
        jobs = ADAPTERS[source](slug)
        if not jobs:
            continue
        comp = score_company(jobs)
        company_rows[slug] = dict(company=slug, source=source, **comp)
        print(f"   {len(jobs)} jobs · footprint={comp['tier']} · {comp['country_count']} countries"
              f" · hires_in_{TARGET_COUNTRY}={comp['hires_in_target']}")
        for j in jobs:
            tier, sig = eligibility(j, comp)
            j["company_footprint"] = comp["tier"]
            j["eligibility"] = tier
            j["restriction_signals"] = sig
            all_jobs.append(j)          # description kept FULL — see below

    # --- de-duplicate to real openings, then re-classify at that level ---
    # v3 fix: descriptions used to be truncated to 600 chars HERE, before the
    # opening-level pass ran. The classifier then read a chopped description
    # and lost every signal past the cut: relocation_only went 410 rows -> 1
    # opening, and description_states_work_from_anywhere 70 -> 0. Truncation
    # now happens last, after both passes, purely to keep the JSON small.
    openings = collapse(all_jobs)
    for g in openings:
        comp = company_rows.get(g["company"])
        comp_min = dict(hires_in_target=comp["hires_in_target"], tier=comp["tier"]) \
            if comp else dict(hires_in_target=False, tier="unknown")
        tier, sig = eligibility(g, comp_min)
        g["eligibility"], g["restriction_signals"] = tier, sig

    for j in all_jobs:
        j["description"] = (j.get("description") or "")[:2000]
    for g in openings:
        g["description"] = (g.get("description") or "")[:2000]

    with open("jobs.json", "w") as f:
        json.dump(all_jobs, f, indent=2)
    with open("companies.json", "w") as f:
        json.dump(list(company_rows.values()), f, indent=2)

    infl = len(all_jobs) / max(len(openings), 1)
    print(f"\n{len(all_jobs)} rows -> {len(openings)} distinct openings"
          f"   (inflation {infl:.2f}x)  from {len(company_rows)} companies")
    print(f"target country: {TARGET_COUNTRY}")

    tally(all_jobs, "ROW LEVEL  (what a naive scraper reports)")
    tally(openings, "OPENING LEVEL  (the honest number)")

    worst = sorted(openings, key=lambda g: -g["rows"])[:8]
    print("\n  most-duplicated openings (rows collapsed):")
    for g in worst:
        print(f"    {g['rows']:3}x  {g['company']:12} {g['title'][:44]}")

    with open("openings.json", "w") as f:
        json.dump(openings, f, indent=2)
    print("\nwrote jobs.json, openings.json, companies.json")


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        main()
