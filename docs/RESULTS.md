# Results and denominators

All values below use frozen evaluator 2.2.1. They are retained observations, not fresh model calls.

| Condition | R | A | B |
|---|---:|---:|---:|
| GPT v1 | 599/600 | 541/600 | 550/600 |
| GPT N2 | 589/600 | 531/600 | 537/600 |
| GPT CS1 | 146/160 | 115/160 | 125/160 |
| Qwen N2 | 69/75 | 62/75 | 69/75 |
| Qwen CS1 | 19/20 | 16/20 | 16/20 |

The GPT record has 624 static allocations and 64 evidence-revision stages across eight product configurations. Qwen contributes 42 first submissions, 39 complete replies, and 38 scorable outputs. There are 723 retained reply files, including one empty file, and seven missing slots.

## Paired comparisons

On 570 common-valid GPT N2 R/A obligations: both correct 526, R-only 34, A-only five, neither five. A minus R is −5.09 percentage points, with an exploratory building-cluster interval [−9.29, −1.55].

On 533 common-valid GPT N2 A/B obligations: both correct 487, A-only 11, B-only 29, neither six. B minus A is +3.38 points, with interval [0.19, 6.42]. On all 600 allocated obligations, the corresponding net gain is six correct readouts (50 rescues and 44 regressions).

For Qwen N2, common-valid R/A has 62 both-correct and one R-only obligation out of 63. Common-valid A/B has 57 both-correct and one both-wrong obligation out of 58, with no rescues or regressions. Its full-allocation B gain therefore should not be presented as the same mechanism as the shared-valid GPT gain.

The intervals resample buildings, retaining the fixed questions and configurations within each sampled building. They use 20,000 saved index draws and seed 20261105. CS1 has two buildings and no broad population interval.

## World coherence and revision

GPT N2 A/B have 69/78 all-relations-correct worlds out of 96 each. Registered geometry passes are 50/49; all-declared passes are 16/13. Joint all-declared successes are 14/13. Three N2 material-blocking worlds have all fixed determinate relations correct. Qwen's 25 valid constructed worlds include no definite material-blocking case, while complex-stair interface errors remain.

Of 64 revision stages, 52 are valid. For the 11 pairs with valid E2 and F2, explicit knowledge states agree in 11/11 and retained relation readouts agree in 51/55. This measures submitted state and selected readouts, not hidden model memory.

The Release contains machine-readable `MAJOR_TABLES.json`, `PAIRED_BOOTSTRAP.json`, per-building/per-configuration tables, and query-level results regenerated from the retained response text.
