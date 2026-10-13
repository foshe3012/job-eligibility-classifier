#!/usr/bin/env python3
"""
Re-score the hand-labelled sample against the CURRENT classifier rules.

sample_to_label.csv stores the verdict v1 gave each posting at the time it was
sampled. That lets you measure v1 (what label_sample.py --score does). This
script re-runs the *current* eligibility() over the same postings so the
before/after comparison is reproducible by anyone who clones the repo, rather
than being a number quoted in the README.

Run in the folder holding job_eligibility.py and sample_to_label.csv:

    python3 rescore.py

IMPORTANT CAVEAT, printed again at the end: the CSV carries the location field
but not the job description, so body-text rules (work-from-anywhere, explicit
restriction phrases, relocation) cannot fire here. This measures the
location-handling rules only, and therefore UNDERSTATES the current version.

stdlib only.
"""

import csv, importlib.util, os, sys
from collections import defaultdict

CSV_PATH = "sample_to_label.csv"
CLF_PATH = "job_eligibility.py"
OPEN_TIERS = {"confirmed_global", "likely_eligible"}


def load_classifier():
    if not os.path.exists(CLF_PATH):
        sys.exit(f"{CLF_PATH} not found — run this in the repo folder.")
    spec = importlib.util.spec_from_file_location("je", CLF_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def binary(verdict):
    if verdict in OPEN_TIERS:
        return "open"
    if verdict == "unclear":
        return "unclear"
    return "restricted"          # includes relocation_only: not remote-eligible


def norm(v):
    v = (v or "").strip().lower()
    if v in ("open", "eligible", "yes"):
        return "open"
    if v in ("restricted", "no"):
        return "restricted"
    if v in ("unclear", "maybe", "?"):
        return "unclear"
    return "skip"                # gone / page not found / blank


def split_locations(cell):
    out = []
    for part in cell.replace("•", ";").replace("|", ";").split(";"):
        part = part.strip()
        if part:
            out.append(part)
    return out


def main():
    je = load_classifier()
    if not os.path.exists(CSV_PATH):
        sys.exit(f"{CSV_PATH} not found.")
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))

    # Neutral company context: no observed hires in the target country, broad
    # footprint. Matches what the classifier knew when the sample was drawn.
    comp = dict(hires_in_target=False, tier="global")

    old_ok = new_ok = n = 0
    changed = []
    still_wrong = []

    print(f"{'id':>3}  {'locations':38}  {'you':<10} {'v1':<17} {'current':<17}")
    print("-" * 94)

    for r in rows:
        truth = norm(r.get("YOUR_VERDICT"))
        if truth == "skip":
            continue
        n += 1
        job = dict(
            locations=split_locations(r.get("locations", "")),
            is_remote=str(r.get("is_remote", "")).strip().lower() == "true",
            description="",                      # not stored — see caveat
        )
        new_verdict, _sig = je.eligibility(job, comp)
        old_verdict = (r.get("script_verdict") or "").strip()

        old_hit = binary(old_verdict) == truth
        new_hit = binary(new_verdict) == truth
        old_ok += old_hit
        new_ok += new_hit

        flag = ""
        if new_hit and not old_hit:
            flag = "  FIXED"
            changed.append(r)
        elif old_hit and not new_hit:
            flag = "  REGRESSED"
            changed.append(r)
        elif not new_hit:
            still_wrong.append((r, truth, new_verdict))

        print(f"{r.get('id',''):>3}  {r.get('locations','')[:38]:38}  "
              f"{truth:<10} {old_verdict:<17} {new_verdict:<17}{flag}")

    print("-" * 94)
    print(f"\n  v1       {old_ok:2}/{n}  = {old_ok/n:.1%}")
    print(f"  current  {new_ok:2}/{n}  = {new_ok/n:.1%}")
    print(f"  delta    {new_ok - old_ok:+d} postings")

    if still_wrong:
        print(f"\n  still wrong ({len(still_wrong)}):")
        for r, truth, new_verdict in still_wrong:
            print(f"    #{r.get('id'):>2} {r.get('company','')[:12]:12} "
                  f"{r.get('locations','')[:34]:34} you={truth:<10} "
                  f"current={new_verdict}")

    print("\n" + "=" * 94)
    print("CAVEAT — read before quoting these figures")
    print("=" * 94)
    print("  sample_to_label.csv stores the location field but not the job")
    print("  description, so the body-text rules cannot fire here:")
    print("    · description_states_work_from_anywhere")
    print("    · relocation_or_sponsorship_offered")
    print("    · must_be_located_in / work_authorisation / residents_only")
    print("  This therefore measures the LOCATION-HANDLING rules only and")
    print("  understates the current version. It is still the honest")
    print("  before/after, because v1 is scored the same way.")
    print()
    print(f"  n={n}. Worst-case 95% margin of error is roughly "
          f"±{1.96*(0.25/n)**0.5*100:.0f}pp.")
    print("  Treat every figure here as directional, not validated.")


if __name__ == "__main__":
    main()
