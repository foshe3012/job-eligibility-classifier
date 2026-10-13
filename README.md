# Job eligibility classifier

Scores live job postings for whether someone resident in a given country could actually hold the role — as opposed to whether the posting says "remote."

Pulls from the public JSON feeds of three applicant tracking systems (Ashby, Greenhouse, Lever). No scraping; these are the same endpoints the job boards themselves consume. Python standard library only, no dependencies.

**Current accuracy: 68% agreement with hand-labelled ground truth (n=28).** That is good enough to prioritise where I spend my own time. It is not good enough to show anyone a verdict badge, and the output is designed accordingly — see *What this doesn't do*.

---

## The problem

"Remote" in a job posting is not a statement about where you may live. A role tagged *Remote* on a job board is routinely restricted to a handful of countries, and the restriction usually lives somewhere other than the field the board indexes — in a region token like `AMER`, in a sentence two-thirds of the way down the description, or nowhere at all.

Scale of it, from the last run: **6,317 postings across 48 companies. 2,592 tagged remote. 83% of those were still location-restricted.**

---

## What it does

```
python3 job_eligibility.py --probe   # resolve company slugs across all three ATSes
python3 job_eligibility.py           # pull, normalise, score
python3 label_sample.py              # draw a stratified sample for hand-labelling
python3 label_sample.py --score      # score the classifier against your labels
python3 boilerplate_check.py         # does a phrase discriminate, or is it template text?
```

- **Three ATS adapters** normalised to one schema.
- **Row-level and opening-level reporting.** Ashby emits one row per job × location, so a role open in eight countries appears eight times. Grouping to distinct openings changes the denominator (measured inflation: 1.13×).
- **Five tiers**, not a binary: `confirmed_global`, `likely_eligible`, `unclear`, `relocation_only`, `restricted`. `relocation_only` exists because an onsite role offering visa sponsorship is a different proposition from a remote role, and merging them hides information.
- **Every verdict carries its signals**, so you can see why.

---

## What was wrong with the first version

This is the part worth reading.

v1 reported that 467 openings were `confirmed_global`. Almost none of them were.

The `WORLDWIDE` pattern included the word **"globally"**, and it was matched against the job *description* rather than the location field. Every company on earth writes "we serve customers globally" or "we're growing our team globally" in its boilerplate. So:

| Posting | v1 verdict |
|---|---|
| Figma — San Francisco, CA · New York, NY | `confirmed_global` |
| Replit — Foster City, CA | `confirmed_global` |
| OpenAI — **Tokyo, Japan** | `confirmed_global` |
| Stripe — San Francisco Or New York | `confirmed_global` |

The tier the tool was most confident about was the one most badly broken.

A second bug: `EMEA` was treated as a region lock. Nigeria is in EMEA. That rule scored 0/2 precision — the only signal with zero.

---

## How I found it

Not by reading the code. By testing the output against reality.

1. **Stratified sample, not random.** 89% of restriction verdicts came from a single signal, so a random sample would have measured that one rule well and the other five not at all. `label_sample.py` round-robins across signals with a floor on the dominant one.
2. **Blind labelling.** 30 postings, every live job page opened and judged by hand, with the classifier's own verdict hidden to avoid anchoring.
3. **Scored against those labels.**

**First pass: 39% agreement. Precision on the `open` class: 0.0%.** Every posting the tool called eligible, I judged not eligible.

The per-signal precision table is what localised the cause — one rule at 100%, one at 0%.

## What changed

- `WORLDWIDE` matched against **location fields only**, never prose. `globally` and `fully global` removed entirely.
- Regions split by whether they **contain** the target country: EMEA, MEA, Africa → eligible-ish. NAMER, AMER, APAC, LATAM, DACH → excluded. (`AMER` was initially unrecognised, found in a later audit.)
- ~70 missing city and country hints added. `Foster City, CA`, `US - Remote` and `Remote, KSA` had been resolving to *no country at all*, which sent them down the optimistic branch.
- **Employer footprint can no longer produce a `confirmed` verdict.** A company's hiring footprint is evidence about the company, not about the job. It now caps at `likely_eligible`.
- An explicit residency statement in the body ("you can work from anywhere in the world") now **outranks** the location field — an office address is not a residency requirement. But where that statement sits alongside a region tag excluding the target, the result is `unclear`, not `confirmed`.

**Re-scored on the same labels: 68%.**

---

## Separating signal from boilerplate

`boilerplate_check.py` exists because of the "globally" failure. It answers one question: does a phrase *discriminate* between an employer's postings, or does it appear on all of them?

- Appears on ~100% of a company's postings → it's in the template. It describes the company, not the job, and cannot override a per-posting field.
- Appears on some but not others → someone made a per-job choice. It should win.

A phrase that sounds permissive is not evidence. "We welcome applicants from any country" is a statement about who may *apply*; it is not a statement about who they can *pay*.

---

## What this doesn't do

- **It does not tell you a given employer will hire you.** Nothing short of asking them does.
- **68% is not production accuracy.** The residual errors are mostly postings where the location field and the body text contradict each other, and a human has to break the tie. That is why `unclear` is a tier rather than a forced binary.
- **It has never seen a confirmed hire.** Across 6,317 postings at 48 companies, not one was posted in Nigeria, so `hires_in_target` was false everywhere and the eligible tier rests on inference rather than observed precedent.
- **Coverage is narrow.** 48 companies is a rounding error against the tens of thousands of boards on these three ATSes, and the eligible tier concentrates in a small number of employers — which may mean coverage is the constraint, or may mean global eligibility genuinely is that concentrated. Unresolved.

---

## Next

Outcome feedback. One button — *"applied, rejected on location"* — turns every use into a labelled example against a specific employer and signal combination. After a few hundred, the weights get fitted rather than guessed, and the accuracy problem starts solving itself.

---

## Files

| | |
|---|---|
| `job_eligibility.py` | Fetch, normalise, score. `--probe` resolves company slugs. |
| `label_sample.py` | Stratified sampler + scorer. `--signal <name>` audits one rule in isolation. |
| `boilerplate_check.py` | Phrase-discrimination test. |
| `form_probe.py` | Checks whether application forms expose an eligible-country list — a direct answer rather than a proxy. |
| `sample_to_label.csv` | The 28 hand-labelled postings the accuracy figures are measured against. |

Built with heavy use of coding agents. The regex that broke it was AI-generated and I approved it; the validation harness that caught it is the part that mattered.
