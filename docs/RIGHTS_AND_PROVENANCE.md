# Rights and data provenance

TopoWorld-Eval is authored by Jincheng Li and Yuxuan Li. Rights differ across the research materials, archival drawings, and third-party software.

## Project materials

No blanket reuse license is granted for the project-authored code, text, annotations, or model-output collection in this release. Public access does not replace permission for uses that require it. Cite the technical report and consult the rights holders before redistribution or relicensing of protected project materials. This statement does not restrict materials that are already public domain or separately licensed.

## Archival drawing pages

The benchmark uses 42 measured-drawing sheets from 14 records in the Library of Congress, Prints & Photographs Division, Historic American Buildings Survey (HABS). The release retains source URLs, survey/call numbers, and SHA-256 image hashes. No private Loft photographs are included.

The [LOC HABS/HAER/HALS rights guidance](https://wwws.loc.gov/rr/print/res/114_habs.html) states that original measured drawings made for the U.S. Government are considered public domain. Item records retain an exception for material copied from other sources. This release uses the selected measured sheets and does not claim a new license over the archival material.

Credit: Library of Congress, Prints & Photographs Division, Historic American Buildings Survey (HABS). The full record and individual sheet list is included as `DRAWING_RIGHTS_AND_ATTRIBUTION.md` in the reproducibility archive; `data/IMAGE_MANIFEST.json` records the image files and hashes.

## Third-party dependencies

The optional macOS arm64 dependency bundle retains the upstream metadata and license files for:

| Distribution | Version | Declared license |
|---|---|---|
| attrs | 26.1.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |

Their licenses apply to those distributions, not automatically to TopoWorld-Eval or the archival drawings. The bundle's native extension is specific to CPython 3.13 on macOS arm64. Other supported Unix environments must install compatible dependencies. Any document-template notices included with the technical-report source remain applicable to those template files.

## Historical outputs and privacy derivatives

The reproduction archive contains 723 existing response files and seven explicit missing allocations. Of the existing replies, 695 are byte-exact historical files and 28 are documented privacy derivatives with personal path strings masked. The export preserves the character and UTF-8 byte counts of modified replies. Invalid and empty outputs remain invalid or empty. The original/private mapping and full chat histories are excluded.

The archive records the derivation and checksums. Model outputs are published as research observations; their inclusion does not grant rights to third-party content beyond the rights that actually apply.
