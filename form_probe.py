#!/usr/bin/env python3
"""
Does the application form expose an ELIGIBLE-COUNTRY list?

If it does, that beats every proxy in the signal list: it is the employer's own
structured answer to "where can you be based", rather than our inference from
prose or posting locations.

This probe does not assume which endpoint carries it. It tries several
candidates per ATS, then walks each JSON response looking for:

  A. a long list of country names        -> a full dropdown (= hires anywhere,
                                            or at least the form allows it)
  B. a SHORT list of country names       -> the actual eligible-country list.
                                            This is the jackpot.
  C. work-authorisation question text    -> which country they require
  D. a location / "where are you based" question of any kind

Run:  python3 form_probe.py
      python3 form_probe.py --dump ashby:supabase     # raw keys for one company

stdlib only. No writes except probe_findings.json.
"""

import json, re, sys, urllib.request, urllib.error
from collections import defaultdict

UA = {"User-Agent": "eligibility-research/0.1"}
TARGET = "nigeria"

# A few companies spanning both ATSes and both ends of the openness spectrum.
SUBJECTS = [
    ("ashby",      "supabase"),
    ("ashby",      "oyster"),
    ("ashby",      "elevenlabs"),
    ("ashby",      "linear"),
    ("greenhouse", "gitlab"),
    ("greenhouse", "canonical"),
    ("greenhouse", "stripe"),
]

# Enough country names to recognise a dropdown without shipping a full ISO list.
COUNTRY_WORDS = {
    "afghanistan", "albania", "algeria", "argentina", "australia", "austria",
    "bangladesh", "belgium", "brazil", "bulgaria", "canada", "chile", "china",
    "colombia", "croatia", "czechia", "denmark", "egypt", "estonia", "finland",
    "france", "germany", "ghana", "greece", "hungary", "india", "indonesia",
    "ireland", "israel", "italy", "japan", "kenya", "latvia", "lithuania",
    "malaysia", "mexico", "morocco", "netherlands", "new zealand", "nigeria",
    "norway", "pakistan", "peru", "philippines", "poland", "portugal",
    "romania", "serbia", "singapore", "slovakia", "slovenia", "south africa",
    "spain", "sri lanka", "sweden", "switzerland", "taiwan", "thailand",
    "turkey", "uganda", "ukraine", "united kingdom", "united states",
    "uruguay", "vietnam", "zambia", "zimbabwe",
}

AUTH_Q = re.compile(
    r"(authoriz|authoris|legally (?:able|entitled) to work|right to work|"
    r"work permit|visa|sponsorship|eligible to work|where (?:are|will) you "
    r"(?:based|located)|country of residence|current location)", re.I)


def fetch(url, quiet=True):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode(errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"__raw__": raw[:20000]}
    except Exception as e:                      # noqa: BLE001 - probe, report all
        if not quiet:
            print(f"    ! {url} -> {e}")
        return None


def walk(node, path="", out=None, depth=0):
    """Yield (path, value) for every leaf and every list-of-strings."""
    if out is None:
        out = []
    if depth > 14:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}.{k}" if path else k, out, depth + 1)
    elif isinstance(node, list):
        strs = [x for x in node if isinstance(x, str)]
        if len(strs) >= 3:
            out.append((path, strs))
        for i, v in enumerate(node):
            if not isinstance(v, str):
                walk(v, f"{path}[{i}]", out, depth + 1)
    elif isinstance(node, str):
        # some ATSes embed the form definition as a JSON string
        s = node.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                walk(json.loads(s), path + "(embedded)", out, depth + 1)
                return out
            except json.JSONDecodeError:
                pass
        out.append((path, [s]))
    return out


def country_hits(values):
    low = {v.strip().lower() for v in values}
    return low & COUNTRY_WORDS


def analyse(label, payload):
    """Return findings dicts for one JSON payload."""
    found = []
    for path, values in walk(payload):
        hits = country_hits(values)
        if len(hits) >= 3:
            found.append(dict(kind="country_list", path=path,
                              n_values=len(values), n_countries=len(hits),
                              target_present=TARGET in hits,
                              sample=sorted(values)[:12]))
        elif len(values) == 1 and AUTH_Q.search(values[0]) and len(values[0]) < 300:
            found.append(dict(kind="auth_or_location_question", path=path,
                              text=values[0][:200]))
    return found


ENDPOINTS = {
    "ashby": [
        "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
        "https://api.ashbyhq.com/posting-api/job-board/{slug}/{jid}",
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting",
    ],
    "greenhouse": [
        "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}?questions=true",
        "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}",
        "https://boards-api.greenhouse.io/v1/boards/{slug}/offices",
        "https://boards-api.greenhouse.io/v1/boards/{slug}?content=true",
    ],
    "lever": [
        "https://api.lever.co/v0/postings/{slug}/{jid}",
        "https://api.lever.co/v0/postings/{slug}?mode=json",
    ],
}

LISTS = {
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
}


def first_job_id(source, slug):
    d = fetch(LISTS[source].format(slug=slug))
    if not d:
        return None
    if source == "lever" and isinstance(d, list):
        return d[0].get("id") if d else None
    jobs = d.get("jobs") or []
    if not jobs:
        return None
    j = jobs[0]
    return j.get("id") or j.get("jobId")


def main():
    results = defaultdict(list)
    print("Probing application-form schemas. One job per company.\n")

    for source, slug in SUBJECTS:
        jid = first_job_id(source, slug)
        print(f"→ {source}:{slug}   job_id={jid}")
        if jid is None:
            print("    (no jobs returned — skipping)")
            continue

        for tmpl in ENDPOINTS[source]:
            url = tmpl.format(slug=slug, jid=jid)
            payload = fetch(url)
            if payload is None:
                print(f"    ✗ {url.split('?')[0].split(slug)[-1] or '/'}  no response")
                continue
            found = analyse(f"{source}:{slug}", payload)
            cl = [f for f in found if f["kind"] == "country_list"]
            qs = [f for f in found if f["kind"] == "auth_or_location_question"]
            tag = "✓" if cl else ("·" if qs else " ")
            print(f"    {tag} {url}")
            for f in cl:
                verdict = ("FULL DROPDOWN (all countries)" if f["n_countries"] > 40
                           else "SHORT LIST  <-- this is the signal")
                print(f"        country list at {f['path']}: "
                      f"{f['n_countries']} countries / {f['n_values']} values, "
                      f"{TARGET} present={f['target_present']}  {verdict}")
                print(f"        sample: {', '.join(f['sample'][:8])}")
            for f in qs[:4]:
                print(f"        question @ {f['path']}: {f['text'][:120]}")
            if found:
                results[f"{source}:{slug}"].append(dict(url=url, found=found))

    with open("probe_findings.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*70}\nHOW TO READ THIS\n{'='*70}")
    print("  SHORT LIST (3-40 countries)  -> the employer's own eligible-country")
    print("     list. Use it directly; it outranks every proxy we discussed.")
    print("  FULL DROPDOWN (40+)          -> the form just offers every country.")
    print("     Tells you nothing about eligibility. Ignore it.")
    print("  Only auth/location questions -> no list, but the question wording")
    print("     names the country they require. Second-best signal.")
    print("  Nothing at all               -> forms are not public on that ATS;")
    print("     drop signal 8 and lean on country breadth + EOR detection.")
    print("\n  wrote probe_findings.json  — paste the console output back.")


if __name__ == "__main__":
    if "--dump" in sys.argv:
        spec = sys.argv[sys.argv.index("--dump") + 1]
        src, slug = spec.split(":")
        jid = first_job_id(src, slug)
        for tmpl in ENDPOINTS[src]:
            url = tmpl.format(slug=slug, jid=jid)
            d = fetch(url)
            print(f"\n--- {url}")
            if d is None:
                print("    no response")
            else:
                print("    top-level keys:",
                      list(d)[:30] if isinstance(d, dict) else f"list[{len(d)}]")
    else:
        main()
