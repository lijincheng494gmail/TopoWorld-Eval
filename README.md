# TopoWorld-Eval

**Grounded, Coherent, and Revisable 3D Worlds from Multi-View Architectural Evidence**

**Jincheng Li · Yuxuan Li**

[Technical report](paper/TopoWorld-Eval_Technical_Report.pdf) · [Supplementary report](paper/TopoWorld-Eval_Supplementary.pdf) · [Reproducibility release](https://github.com/lijincheng494gmail/TopoWorld-Eval/releases/tag/v1.0.0) · [Evaluation protocol](docs/EVALUATION_PROTOCOL.md)

## Overview

TopoWorld-Eval is a **benchmark, executable evaluation framework, and empirical analysis** of multimodal spatial understanding. Models inspect architectural drawings, answer spatial questions, construct a bounded 3D world, and revise that world when evidence changes. The evaluator reads relations from actual submitted geometry and identity bindings, then checks geometry, visual localization, and evidence state separately. The project does not introduce a newly trained neural network.

## Scientific Question

> Can multimodal models maintain a grounded, coherent, and revisable 3D world across multiple views and tasks?

Correct answers to individual spatial questions need not establish that the model can construct and maintain a single world satisfying those answers. TopoWorld measures both tasks on the same evidence.

## Benchmark and Tasks

The retained study uses **14 buildings, 42 public measured-drawing pages, 95 determinate reference relations, and one unresolved identity relation**. The pages include plans, elevations, and sections. Targets are point-anchored fragments; this is not unrestricted whole-building object discovery.

| Route | Input | Output |
|---|---|---|
| **R: direct answering** | Assigned drawings, targets, and fixed questions | Relation answers with evidence references |
| **A: independent construction** | Same core evidence and world contract | Executable world JSON |
| **B: relation-assisted construction** | A inputs plus correct determinate relations | Executable world JSON |

Routes use independent contexts. A does not read R; B does not read A. **N2** uses neutral point and class anchors for 12 buildings. **CS1** adds target-unit hints for two complex-stair buildings. Historical **v1** reuses the 12 N2 buildings with richer semantic locators and is reported separately. Evidence-revision tasks add, withdraw, and freshly reprocess source evidence.

## Evaluation Protocol

The world representation is **W = (O, G, α, R, P)**: physical entities, executable geometry, observation-to-entity bindings, typed spatial relations, and evidence provenance. Supported primitives include boxes, box unions, straight stair runs, and explicit unknown geometry.

The frozen **2.2.1** instrument separates:

- Delivery, strict JSON, Schema, and compilation validity.
- Fixed relation readouts from the submitted world.
- **Registered geometry:** target roles and their dependency closure.
- **All-declared geometry:** additional structures the model chose to generate.
- Point-assisted visual localization and cross-view identity.
- Source activity, explicit knowledge state, and retained relations after revision.

First outputs and failures are retained without answer repair. Full-allocation and common-valid paired denominators are both reported. Geometry checks concern represented fragments; they do not certify full human clearance or building-code compliance.

## Main Results

Correct determinate answers/readouts, including missing and invalid allocations:

| Model/interface condition | R | A | B |
|---|---:|---:|---:|
| GPT/Codex, N2 | 589/600 | 531/600 | 537/600 |
| GPT/Codex, CS1 | 146/160 | 115/160 | 125/160 |
| Qwen API, N2 | 69/75 | 62/75 | 69/75 |
| Qwen API, CS1 | 19/20 | 16/20 | 16/20 |

GPT results pool eight recorded product configurations from one provider family. On 570 common-valid N2 R/A obligations, 34 are R-correct/A-incorrect and five show the reverse. On 533 common-valid A/B obligations, relation assistance rescues 29 and loses 11. These comparisons measure independent task performance, not a shared hidden model state.

The record contains **688 GPT stages** (624 static tasks and 64 revision stages) and **42 Qwen submissions**. Qwen returned 39 complete replies, of which 38 were scorable. GPT Codex and Qwen API have different tool access and inference controls; the results are not an equal-compute model ranking. See [results and denominators](docs/RESULTS.md).

## Installation

Use **Python 3.13** in a dedicated environment:

```sh
git clone https://github.com/lijincheng494gmail/TopoWorld-Eval.git
cd TopoWorld-Eval
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The frozen worker uses Unix resource limits. Windows is unsupported by this release. Platform evidence and exact dependency versions are recorded in [reproducibility documentation](docs/REPRODUCIBILITY.md).

## Quick Start

Check a small synthetic example using the released geometry code:

```sh
python scripts/check_example.py
```

For the full frozen-output study, download the Release archive, verify its pinned SHA-256, and extract it outside Git history:

```sh
python scripts/download_release.py --output artifacts/reproducibility
python scripts/reproduce.py --package artifacts/reproducibility --output runs/replay01 --tables runs/tables01
```

This reevaluates the retained responses and regenerates the main tables. It requires no model, API key, account, or original research workspace. Use a new output directory for each run.

## Reproducibility

Offline acceptance reproduces **730/730 frozen scientific scoring signatures** and the principal tables. This means deterministic scoring agrees with the frozen record, including its failures; it does not mean 730 correct model outputs or reproducible proprietary model sampling.

The [versioned Release](https://github.com/lijincheng494gmail/TopoWorld-Eval/releases/tag/v1.0.0) holds the complete package: images, task prompts, references, retained responses, frozen scorers, dependencies, and expected tables. Large assets are not stored in normal Git history. The package records its derivation from the accepted local scientific snapshot. Of 723 retained response files, 695 are byte-exact originals and 28 retain previously documented, length-preserving personal-path masking. Seven missing allocations and one empty response remain unchanged.

## Data Provenance

Images are HABS measured-drawing sheets held by the **Library of Congress, Prints & Photographs Division**. Per-sheet URLs and hashes are included. LOC identifies original government measured drawings as public-domain works while retaining exceptions for third-party copies. Private Loft photographs are excluded. See [drawing attribution](docs/DRAWING_RIGHTS_AND_ATTRIBUTION.md) and [rights and provenance](docs/RIGHTS_AND_PROVENANCE.md). Third-party material is not relicensed by this repository.

## Limitations

The study covers a small set of public drawings and bounded target fragments. Public-source pretraining exposure is unknown. Layout-family independence is not established. Product labels do not establish immutable neural checkpoints. Point-assisted localization is not full-image detection. Several geometry encodings, including a documented slab-equivalence limitation, remain outside reliable interpretation. Successful source-state fields do not prove erasure of hidden model memory. Positive constructions, delivery failures, unsupported certainty, and definite geometry errors remain in the record.

## Citation

Please cite the technical report as a research artifact:

```bibtex
@misc{li2026topoworld,
  title = {TopoWorld-Eval: Grounded, Coherent, and Revisable 3D Worlds from Multi-View Architectural Evidence},
  author = {Li, Jincheng and Li, Yuxuan},
  year = {2026},
  howpublished = {Technical report},
  url = {https://github.com/lijincheng494gmail/TopoWorld-Eval}
}
```

Machine-readable metadata are in [CITATION.cff](CITATION.cff). Reuse terms are stated separately in [LICENSE_NOTICE.md](LICENSE_NOTICE.md); no project-wide third-party license is implied.
