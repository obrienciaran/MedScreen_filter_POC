# Data folders

Two folders hold example PubMed papers you can run the filter on. They show the
filter working in two opposite ways. Two more hold single-paper case studies (see
`eval/README.md`): `bixonimania_live` (a fabricated, non-existent condition that the
filter leaves `ungrounded`) and `retracted_drop_live` (a formally retracted paper the
filter `drop`s via the retraction fast path).

## trial

A hand picked set of 10 papers. Most of them have been retracted, so the filter
should flag them as bad and drop them. A few solid papers are mixed in as a
check. Use this set to see that the filter catches bad papers.

Built by `scripts/fetch_trial_xml.py`.

## representative

A plain sample of 10 recent papers across common areas of medicine. Retracted
papers are left out on purpose. These are normal papers, so the filter should
keep most of them. Use this set to see that the filter does not wrongly flag
good papers.

Built by `scripts/fetch_representative_xml.py`.
