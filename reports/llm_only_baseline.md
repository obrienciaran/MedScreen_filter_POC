# LLM-only factuality baseline

An LLM-only baseline that judges each gold claim's truthfulness **from the model's own
knowledge, with no retrieval**, to answer the question: is an evidence-retrieval filter worth its
complexity when a capable model already knows most medical consensus?

- **Model:** `gemini-2.5-flash-lite` (paid key), one call per claim, no evidence supplied.
- **Data:** the 64-claim gold set (32 reversed = 28 reversals + 4 fabrications, 32 still-true
  controls).
- **Ground truth:** a reversed or fabricated claim is false (the model should reject it); a
  control is true (the model should keep it).
- **Script:** `medscreen_poc`-independent harness in the run log; prompt asks for a JSON
  `supported` / `confidence` / `rationale`.

## Results

| Metric | Result |
|---|---|
| Accuracy | **62 / 64 = 96.9%** |
| Reversed claims correctly rejected | 30 / 32 |
| Controls correctly kept | 32 / 32 |
| False negatives (false claim kept) | 2 |
| False positives (control dropped) | 0 |

## The two misses

Both false negatives are the instructive cases, and they mark exactly where evidence retrieval
and the paper's own XML earn their keep:

- **`macchiarini-trachea` (a fabrication).** The model judged the stem-cell tracheal-transplant
  claim *truthful*. It has no way to know the work was fraudulent and formally retracted in 2023;
  a retraction that post-dates or is under-represented in training is invisible to native
  knowledge. In the filter this paper is dropped immediately by the **retraction fast path**,
  reading the `RetractionIn` link straight from the XML, with no LLM call at all.
- **`orbita-pci-angina-symptoms` (a contested reversal).** ORBITA's sham-controlled result is
  still debated, so the model siding with "PCI relieves angina" is the genuinely hard, nuanced
  case — difficult for either approach.

## Reading

The baseline reproduces the ~96.9% that a direct LLM fact-check reaches on this kind of set, and
it confirms the pattern the project is built around: **native model knowledge is excellent on
famous, well-settled reversals, but blind to fabrications and retractions it was never taught,
and shaky on contested cases.** Those are precisely the situations evidence retrieval and the
retraction fast path are designed for. The benchmark here is also the friendly tail — famous
reversals are maximally in-distribution for the model — so it understates retrieval's value;
post-cutoff and long-tail cases (future work) would widen the gap.

The honest conclusion is not "retrieval beats the LLM" but that the two cover different failure
modes: the LLM is a strong, cheap first pass, and retrieval plus the XML retraction signal cover
what the model cannot know. The production design keeps the LLM confined to extraction and stance
and lets retrieved, tier-weighted evidence (and the retraction fast path) drive the verdict.
