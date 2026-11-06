# Public technical reports

**Authors:** Jincheng Li and Yuxuan Li, in that order.

- [Technical report](TopoWorld-Eval_Technical_Report.pdf): the research question, benchmark, executable evaluation, and principal results.
- [Supplementary report](TopoWorld-Eval_Supplementary.pdf): source qualification, exact protocols, full results, evidence revision, case studies, and reproducibility details.

These are independently prepared public derivatives of the frozen research documents. Author names and publication-neutral presentation replace anonymous review formatting. Scientific sections, result tables, and figure content are retained. The derivation and source hashes are recorded in `PUBLIC_PAPER_PROVENANCE.json`.

## Build from source

Prepare an existing LaTeX installation with `pdflatex`, `bibtex`, and the packages imported by the source. The scripts do not install packages or contact a model service. From the repository root:

```sh
python3 paper/source/main/build_pdf.py --output paper/TopoWorld-Eval_Technical_Report.pdf
python3 paper/source/supplementary/build_pdf.py --output paper/TopoWorld-Eval_Supplementary.pdf
```

Each source directory writes intermediate files to its own ignored `build/` directory. Use `--build-dir` to select another location. Source paths are relative to the individual project directory.

The source provides a rebuildable report, rather than a complete TeX distribution. See [typesetting attribution](THIRD_PARTY_TEX.md) for third-party components. No author contribution statement, institutional affiliation, or collaborator account is inferred.
