#!/usr/bin/env python3
"""
Ground-truth sampler and scorer for the eligibility classifier.

Two modes:

  python3 label_sample.py            -> writes sample_to_label.csv (30 rows)
  python3 label_sample.py --score    -> reads sample_to_label.csv back,
                                        prints precision / recall / per-signal
                                        accuracy, and lists every disagreement

Why stratified and not random: 89% of restrictions come from one signal
(job_location_country_mismatch). A uniform random sample would spend almost
every row on that signal and tell you nothing about the other five. This
over-samples the rare signals deliberately, then re-weights at scoring time.

stdlib only.
"""

import csv, json, os, random, sys
from collections import defaultdict, Counter

IN_JSON  = "openings.json"
CSV_PATH = "sample_to_label.csv"
TARGET   = "Nigeria"          # label text only; the classifier owns the real one
SEED     = 20260930          # fixed, so the sample is reproducible

N_RESTRICTED    = 15
N_OPEN          = 12
N_UNCLEAR       = 3
DOMINANT_FLOOR  = 6     # min rows given to the largest restriction signal

OPEN_TIERS = {"confirmed_global", "likely_eligible"}

FIELDS = ["id", "company", "title", "locations", "is_remote",
          "script_verdict", "script_signals", "url",
          "YOUR_VERDICT", "NOTES"]

HELP = """
HOW TO LABEL
------------
Open sample_to_label.csv in Excel or Numbers. For each row, open the URL and
decide ONE thing only:

    Could someone living in Nigeria hold this job?

Put one of these in YOUR_VERDICT:

    open        the posting allows a Nigeria-based hire (or says worldwide /
                explicitly lists Nigeria / states no location requirement)
    restricted  the posting requires a location, region, or work authorisation
                that excludes Nigeria
    unclear     you genuinely cannot tell from the posting

Leave NOTES for anything surprising - especially a posting whose location
field and body text disagree. Those are the cases that matter most.

Rules that keep this honest:
  - Do not look at script_verdict before deciding. Hide those columns first.
  - "Remote" alone is not "open". Look for the country or region list.
  - If the page is 404 or the role is closed, write: gone
  - Label all 30. A partial sample skews toward the easy ones.

Then: python3 label_sample.py --score
"""


def load():
    if not os.path.exists(IN_JSON):
        sys.exit(f"{IN_JSON} not found. Run job_eligibility.py first "
                 f"(in this same folder).")
    with open(IN_JSON) as f:
        return json.load(f)


def first_url(g):
    u = g.get("urls") or []
    return u[0] if u else ""


def stratified(openings):
    """Spread the restricted rows across signals instead of piling into one."""
    rng = random.Random(SEED)

    by_tier = defaultdict(list)
    for i, g in enumerate(openings):
        g["_i"] = i
        by_tier[g.get("eligibility", "unknown")].append(g)

    restricted = [g for t, rows in by_tier.items() if t == "restricted"
                  for g in rows]
    by_signal = defaultdict(list)
    for g in restricted:
        sig = (g.get("restriction_signals") or ["<none>"])[0]
        by_signal[sig].append(g)

    for rows in by_signal.values():
        rng.shuffle(rows)

    picked = []
    cursors = defaultdict(int)

    # The dominant signal decides ~89% of verdicts, so give it a floor of 6 —
    # enough to notice if it is badly wrong. Equal round-robin would leave it
    # with 3, which measures the rare signals well and the important one badly.
    if by_signal:
        dom = max(by_signal, key=lambda s: len(by_signal[s]))
        floor = min(DOMINANT_FLOOR, len(by_signal[dom]), N_RESTRICTED)
        picked += by_signal[dom][:floor]
        cursors[dom] = floor

    order = sorted(by_signal, key=lambda s: len(by_signal[s]))
    while len(picked) < N_RESTRICTED and any(
            cursors[s] < len(by_signal[s]) for s in order):
        for s in order:
            if len(picked) >= N_RESTRICTED:
                break
            if cursors[s] < len(by_signal[s]):
                picked.append(by_signal[s][cursors[s]])
                cursors[s] += 1

    openrows = [g for t in OPEN_TIERS for g in by_tier.get(t, [])]
    rng.shuffle(openrows)
    unclear = list(by_tier.get("unclear", []))
    rng.shuffle(unclear)

    sample = picked + openrows[:N_OPEN] + unclear[:N_UNCLEAR]
    rng.shuffle(sample)                      # so verdicts aren't clustered
    return sample


def write_csv(sample):
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for n, g in enumerate(sample, 1):
            w.writerow({
                "id": n,
                "company": g.get("company", ""),
                "title": g.get("title", ""),
                "locations": " | ".join(g.get("locations") or []),
                "is_remote": g.get("is_remote"),
                "script_verdict": g.get("eligibility", ""),
                "script_signals": ",".join(g.get("restriction_signals") or []),
                "url": first_url(g),
                "YOUR_VERDICT": "",
                "NOTES": "",
            })


def do_sample():
    openings = load()
    sample = stratified(openings)
    write_csv(sample)

    tiers = Counter(g.get("eligibility") for g in sample)
    sigs = Counter((g.get("restriction_signals") or ["<none>"])[0]
                   for g in sample if g.get("eligibility") == "restricted")
    missing_url = sum(1 for g in sample if not first_url(g))

    print(f"wrote {CSV_PATH}  ({len(sample)} rows, seed {SEED})\n")
    print("  script verdict mix:")
    for t, c in tiers.most_common():
        print(f"    {t:18} {c:3}")
    print("\n  restricted rows by signal:")
    for s, c in sigs.most_common():
        print(f"    {s:34} {c:3}")
    if missing_url:
        print(f"\n  ! {missing_url} rows have no URL — label those from the "
              f"locations column or skip and note 'no-url'")
    print(HELP)


# ------------------------------------------------------------------ scoring
def norm(v):
    v = (v or "").strip().lower()
    if v in ("open", "eligible", "yes", "y"):
        return "open"
    if v in ("restricted", "no", "n", "closed"):
        return "restricted"
    if v in ("unclear", "?", "maybe"):
        return "unclear"
    if v in ("gone", "404", "expired", "no-url", "page not found",
             "not found", "closed role", "dead", "removed"):
        return "gone"
    return ""


def script_binary(v):
    return "open" if v in OPEN_TIERS else ("unclear" if v == "unclear"
                                           else "restricted")


def do_score():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"{CSV_PATH} not found. Run without --score first.")
    with open(CSV_PATH) as f:
        rows = list(csv.DictReader(f))

    labelled, skipped, blank = [], 0, 0
    for r in rows:
        y = norm(r["YOUR_VERDICT"])
        if y == "gone":
            skipped += 1
        elif not y:
            blank += 1
        else:
            labelled.append((r, y))

    if not labelled:
        sys.exit("No usable labels found in YOUR_VERDICT.")

    print(f"{len(labelled)} labelled · {skipped} gone · {blank} blank\n")
    if blank:
        print(f"  ! {blank} rows unlabelled — results below are partial "
              f"and biased toward whatever you did label\n")

    # confusion matrix, script (rows) x you (cols)
    keys = ["open", "restricted", "unclear"]
    cm = {a: {b: 0 for b in keys} for a in keys}
    for r, y in labelled:
        cm[script_binary(r["script_verdict"])][y] += 1

    w = 12
    print("  confusion matrix   (script down, you across)")
    print("    " + "".join(f"{k:>{w}}" for k in [""] + keys))
    for a in keys:
        print("    " + f"{a:<{w}}" + "".join(f"{cm[a][b]:>{w}}" for b in keys))

    def pr(cls):
        tp = cm[cls][cls]
        fp = sum(cm[cls][b] for b in keys if b != cls)
        fn = sum(cm[a][cls] for a in keys if a != cls)
        p = tp / (tp + fp) if tp + fp else 0.0
        r_ = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r_ / (p + r_) if p + r_ else 0.0
        return p, r_, f1, tp, fp, fn

    print("\n  per class")
    for cls in ("restricted", "open"):
        p, r_, f1, tp, fp, fn = pr(cls)
        print(f"    {cls:11} precision {p:5.1%}  recall {r_:5.1%}  "
              f"F1 {f1:5.1%}   (tp {tp} fp {fp} fn {fn})")

    agree = sum(cm[k][k] for k in keys)
    print(f"\n  overall agreement  {agree}/{len(labelled)} "
          f"= {agree/len(labelled):.1%}")

    # per-signal accuracy: which signal is actually trustworthy
    sig_stat = defaultdict(lambda: [0, 0])
    for r, y in labelled:
        if script_binary(r["script_verdict"]) != "restricted":
            continue
        for s in (r["script_signals"] or "<none>").split(","):
            s = s.strip() or "<none>"
            sig_stat[s][1] += 1
            if y == "restricted":
                sig_stat[s][0] += 1
    if sig_stat:
        print("\n  precision by restriction signal")
        for s, (ok, tot) in sorted(sig_stat.items(), key=lambda x: -x[1][1]):
            print(f"    {s:34} {ok:3}/{tot:<3} {ok/tot:6.1%}")

    dis = [(r, y) for r, y in labelled
           if script_binary(r["script_verdict"]) != y]
    print(f"\n  disagreements ({len(dis)}) — read every one of these:")
    for r, y in dis:
        print(f"\n    #{r['id']} {r['company']} · {r['title'][:52]}")
        print(f"       script: {r['script_verdict']:17} "
              f"[{r['script_signals']}]")
        print(f"       you:    {y}")
        print(f"       locs:   {r['locations'][:90]}")
        if r["NOTES"].strip():
            print(f"       notes:  {r['NOTES'][:110]}")
        if r["url"]:
            print(f"       {r['url']}")

    n = len(labelled)
    moe = 1.96 * (0.25 / n) ** 0.5
    print(f"\n  n={n}. Worst-case 95% margin of error is about "
          f"±{moe*100:.0f}pp, so treat any figure here as directional. "
          f"A signal below ~70% precision needs fixing before launch; "
          f"one above ~90% on n<10 is not yet proven.")


def do_signal(signal, n=15):
    """Audit ONE signal in isolation, with the matching sentence extracted.

    Use when a single rule carries a large share of verdicts and you need to
    know whether the rule is reading English correctly. Writes
    signal_<name>.csv with a QUOTE column already filled from the description,
    so you are checking wording, not hunting for it.
    """
    import re
    openings = load()
    hits = [g for g in openings
            if signal in (g.get("restriction_signals") or [])]
    if not hits:
        avail = Counter(s for g in openings
                        for s in (g.get("restriction_signals") or []))
        print(f"No openings carry '{signal}'. Available:\n")
        for s, c in avail.most_common():
            print(f"    {s:44} {c:5}")
        return

    rng = random.Random(SEED)
    rng.shuffle(hits)
    sample = hits[:n]

    # pull the sentence that most likely triggered the rule
    TRIGGERS = re.compile(
        r"[^.!?\n]*\b(anywhere|any country|relocat|sponsor|distributed|"
        r"location[- ]independent|worldwide|no location)\b[^.!?\n]*[.!?]?", re.I)

    out = f"signal_{signal}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "company", "title", "locations", "verdict",
                    "QUOTE_FROM_POSTING", "url", "RULE_CORRECT", "NOTES"])
        for i, g in enumerate(sample, 1):
            quotes = TRIGGERS.findall(g.get("description") or "")
            full = TRIGGERS.finditer(g.get("description") or "")
            snip = " || ".join(m.group(0).strip() for m in full)[:400]
            w.writerow([i, g.get("company"), g.get("title"),
                        " | ".join(g.get("locations") or []),
                        g.get("eligibility"), snip, first_url(g), "", ""])

    print(f"wrote {out}  ({len(sample)} of {len(hits)} openings "
          f"carrying '{signal}')\n")
    print("  Read QUOTE_FROM_POSTING. Put yes/no in RULE_CORRECT:")
    print(f"    yes  the quoted wording really does mean someone in "
          f"{TARGET} may hold this job")
    print("    no   the wording is boilerplate, is about who may APPLY, or")
    print("         is about relocating TO an office\n")
    print("  Descriptions here are truncated to 600 chars, so some quotes")
    print("  will be empty — open the URL for those.\n")
    print(f"  If more than ~3 of 15 come back 'no', the rule is doing the "
          f"same thing\n  the word 'globally' did, and the "
          f"confirmed_global tier is overstated.")


if __name__ == "__main__":
    if "--score" in sys.argv:
        do_score()
    elif "--signal" in sys.argv:
        i = sys.argv.index("--signal")
        sig = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        do_signal(sig or "description_states_work_from_anywhere")
    else:
        do_sample()
