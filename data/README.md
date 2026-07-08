# Data folders

Sample PubMed papers to run the filter on. Each folder shows the filter working in a different
way.

## gold

The labelled test set (`gold/consensus_reversals.yaml`). It holds medical claims the field is
known to have reversed, each tagged with the study that overturned it, plus still-true controls.
This is what the filter's accuracy is measured against. See `eval/README.md`.

## representative

A sample of 30 recent papers across common areas of medicine, with retracted papers left out on
purpose. These are ordinary papers, so the filter should keep almost all of them. Use this set to
check that the filter does not wrongly flag good papers, and to measure how often it does.

Built by `scripts/fetch_representative_xml.py`:

```bash
python scripts/fetch_representative_xml.py --out-dir data/representative
medscreen-filter --input data/representative --out-csv reports/representative.csv
python scripts/flag_audit.py --csv reports/representative.csv
```

`flag_audit.py` reads the filter output (offline, no LLM) and reports how the papers split across
keep, down-weight, drop, and review, and lists the ones that were not kept. On a set of ordinary
papers, every paper the filter did not keep is a possible false positive worth a look.

## trial

A hand-picked set of 10 papers, most of them retracted. The filter should flag those as bad and
drop them, with a few solid papers mixed in as a check. Use this set to see that the filter
catches bad papers. Built by `scripts/fetch_trial_xml.py`.

## Single-paper case studies

Two folders hold one paper each, to show a single verdict (see `eval/README.md`):

- `bixonimania_live`: a made-up condition that does not exist. There is nothing to retrieve, so
  the filter leaves it `ungrounded` and flags it for review rather than passing it.
- `retracted_drop_live`: a formally retracted paper. The filter drops it straight away by reading
  the retraction link in its own XML, with no LLM call.
