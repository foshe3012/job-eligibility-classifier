#!/usr/bin/env python3
"""
Does a phrase DISCRIMINATE between postings, or is it company boilerplate?

The question this settles: when a posting says "work from anywhere" but is
tagged to a region, which field is telling the truth?

  - If the phrase appears on ~100% of that employer's postings, it is pasted
    into the template. It says something about the COMPANY and nothing about
    the JOB, so it cannot override a per-posting location tag.
  - If it appears on some postings and not others, the employer is making a
    per-job statement. It should beat the tag.

Run in the folder holding jobs.json:   python3 boilerplate_check.py

stdlib only.
"""

import json, os, re, sys
from collections import defaultdict

PHRASES = {
    "work_from_anywhere": re.compile(
        r"work from anywhere|you (?:can|may) (?:live|work|be based) anywhere|"
        r"hire (?:people )?anywhere|anywhere in the world", re.I),
    "fully_remote_distributed": re.compile(
        r"fully (?:remote|distributed)|100% remote|remote[- ]first", re.I),
    "relocation_or_visa": re.compile(
        r"relocation (?:assistance|support|package)|sponsor (?:work )?visas?|"
        r"visa sponsorship", re.I),
}

REGION = re.compile(
    r"\b(amer|namer|emea|apac|apj|latam|global|worldwide|anz|dach|"
    r"north america|europe|americas)\b", re.I)


def main():
    if not os.path.exists("jobs.json"):
        sys.exit("jobs.json not found — run job_eligibility.py in this folder first.")
    jobs = json.load(open("jobs.json"))

    by_co = defaultdict(list)
    for j in jobs:
        by_co[j.get("company", "?")].append(j)

    for pname, pat in PHRASES.items():
        print(f"\n{'='*74}\nPHRASE: {pname}\n{'='*74}")
        print(f"  {'company':14} {'hits':>5} {'/ jobs':>7} {'rate':>7}   verdict")
        rows = []
        for co, js in by_co.items():
            hits = sum(1 for j in js if pat.search(j.get("description") or ""))
            if not hits:
                continue
            rate = hits / len(js)
            rows.append((rate, co, hits, len(js)))
        if not rows:
            print("    (no matches)")
            continue
        for rate, co, hits, tot in sorted(rows, reverse=True):
            if rate >= 0.95:
                v = "BOILERPLATE — cannot override a per-job tag"
            elif rate >= 0.6:
                v = "mostly template — weak evidence"
            else:
                v = "DISCRIMINATES — per-job statement, should win"
            print(f"  {co:14} {hits:5} {tot:7} {rate:6.0%}   {v}")

        # for the discriminating ones, show how the phrase splits by region tag
        print("\n  phrase presence by region tag (companies where it varies):")
        shown = 0
        for rate, co, hits, tot in sorted(rows, reverse=True):
            if rate >= 0.95 or shown >= 6:
                continue
            tags = defaultdict(lambda: [0, 0])
            for j in by_co[co]:
                locs = " ".join(j.get("locations") or []) or "(none)"
                m = REGION.search(locs)
                key = m.group(0).upper() if m else locs[:18]
                tags[key][1] += 1
                if pat.search(j.get("description") or ""):
                    tags[key][0] += 1
            line = "  ".join(f"{k}={h}/{t}" for k, (h, t) in
                             sorted(tags.items(), key=lambda x: -x[1][1])[:6])
            print(f"    {co:14} {line}")
            shown += 1

    print(f"\n{'='*74}")
    print("READ IT THIS WAY")
    print(f"{'='*74}")
    print("  A phrase at 100% for an employer is in their template. It tells")
    print("  you the company is remote-friendly; it does NOT tell you this")
    print("  particular job is open to your country, so the location tag is")
    print("  the only field carrying job-level information.")
    print()
    print("  A phrase that varies — present on the Global postings, absent on")
    print("  the AMER ones, say — is a deliberate per-job statement, and it")
    print("  should outrank the tag.")
    print()
    print("  Paste this output back and the precedence rule gets set by the")
    print("  data instead of by either of us arguing from intuition.")


if __name__ == "__main__":
    main()
