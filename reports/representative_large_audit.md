# Over-flag audit (presumed-keep set)

- Source CSV: `reports/representative_large.csv`
- Papers: 30
- **Over-flag rate: 80%** (24/30 not kept)

On an ordinary, non-retracted set the expected action is `keep`. Each flagged paper below
is a candidate false positive: either a real issue the filter caught or an over-flag to
investigate. Read `refuting_pmids` and `notes` to see what drove the flag.

## Action distribution

| Action | Count |
|---|---|
| `keep` | 6 |
| `drop` | 2 |
| `downweight` | 22 |

## Flagged papers

| pmid | title | verdict | action | score | n_claims | n_refuted_claims | top_refuting_tier | refuting_confidence | refuting_pmids | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 38383266 | Epidemiology, treatment and prognosis of HIV infection in 2… | refuted | drop | 0.000 | 5 | 1 | 0.80 | 0.90 | 34718462 |  |
| 38469546 | Rheumatoid arthritis: pathogenesis and therapeutic advances. | refuted | drop | 0.000 | 5 | 1 | 0.80 | 0.90 | 37591216;38806190;39075620;40245585 |  |
| 40057344 | Tuberculosis. | contested | downweight | 0.000 | 5 | 0 | 0.90 | 1.00 | 41578833 |  |
| 40334018 | Immunotherapy for resectable lung cancer. | contested | downweight | 0.084 | 5 | 0 | 0.90 | 0.80 | 41038207 |  |
| 41192690 | Chronic hepatitis B in 2025: diagnosis, treatment and futur… | contested | downweight | 0.292 | 5 | 0 | 0.90 | 0.90 | 36586590;37074026;39425534 |  |
| 41110447 | Community-acquired pneumonia. | contested | downweight | 0.322 | 5 | 0 | 0.50 | 0.80 | 39718980;39988242;41340493 |  |
| 38573470 | What Causes Premature Coronary Artery Disease? | contested | downweight | 0.372 | 5 | 0 | 0.40 | 0.90 | 38881049 |  |
| 40329642 | Advancing an Inflammatory Subtype of Major Depression. | contested | downweight | 0.378 | 5 | 0 | 0.40 | 0.90 | 21276847;39798913;42205644 |  |
| 38418309 | Advances in heart failure management. | contested | downweight | 0.442 | 2 | 0 | 0.40 | 0.80 | 41529956 |  |
| 37913929 | Atrial fibrillation and stroke: State-of-the-art and future… | contested | downweight | 0.444 | 5 | 0 | 0.40 | 1.00 | 38983168 |  |
| 39496213 | Contemporary Management of Acute Ischemic Stroke. | contested | downweight | 0.451 | 4 | 0 | 0.40 | 0.90 | 34035152 |  |
| 38880666 | Nevi and Melanoma. | contested | downweight | 0.468 | 5 | 0 | 0.40 | 0.80 | 40057604 |  |
| 38619053 | Vestibular migraine: an update. | contested | downweight | 0.500 | 5 | 0 | 0.00 | 0.00 |  |  |
| 39092891 | Review: sepsis guidelines and core measure bundles. | contested | downweight | 0.500 | 5 | 0 | 0.00 | 0.00 |  |  |
| 39185405 | Inflammation mechanism and research progress of COPD. | contested | downweight | 0.500 | 5 | 0 | 0.00 | 0.00 |  |  |
| 38821639 | Molecular Pathology of Prostate Cancer. | contested | downweight | 0.538 | 5 | 0 | 0.40 | 0.80 | 42204638 |  |
| 38777539 | Hereditary Breast Cancer: BRCA Mutations and Beyond. | contested | downweight | 0.544 | 4 | 0 | 0.40 | 0.80 | 29368626;29777908 |  |
| 38934234 | Diagnosis and management of inflammatory bowel disease. | contested | downweight | 0.600 | 5 | 0 | 0.40 | 0.90 | 40769616 |  |
| 40185518 | Pathogenesis of Parkinson's Disease. | contested | downweight | 0.643 | 5 | 0 | 0.40 | 0.80 | 25904081 |  |
| 39051318 | Global Initiative for Asthma Guidelines 2024: An Update. | contested | downweight | 0.660 | 5 | 0 | 0.00 | 0.00 |  |  |
| 39250809 | Knee Osteoarthritis. | contested | downweight | 0.660 | 5 | 0 | 0.00 | 0.00 |  |  |
| 39084811 | Diagnosis and Treatment of Hyperglycemia in Pregnancy: Type… | contested | downweight | 0.754 | 2 | 0 | 0.00 | 0.00 |  |  |
| 39448132 | Postmenopausal Osteoporosis: A Review of Latest Guidelines. | contested | downweight | 0.771 | 3 | 0 | 0.00 | 0.00 |  |  |
| 38677823 | Screening for Colorectal Cancer. | contested | downweight | 0.900 | 2 | 0 | 0.00 | 0.00 |  |  |
