# Trial release checks

## Technical

- Run unit tests and a real-score batch that covers long scores, Chinese paths, duplicate part names, and one invalid file.
- Inspect rendered first, middle, and final pages for each sample score; compare notes and expressions with the source in an editor.
- Install the Windows package on a clean Windows machine and process a sample score. The build self-test alone does not establish clean-machine compatibility.
- Confirm HTTPS, unique invitation tokens, persistent quota storage, and operator monitoring before enabling online AI.
- Check AI findings with human reviewers; measure useful findings, false alarms, and missed issues.

## License and privacy

- This repository currently has **no top-level software license**. Publishing source does not grant a general reuse license. Select and add a license before broader distribution.
- Verovio: LGPL-3.0-only (Python package metadata). PySide6 Essentials: LGPL-3.0-only or GPL alternatives. Keep their copyright/license notices in distributions and review applicable dynamic-linking obligations.
- svglib: LGPL-3.0-or-later. ReportLab: BSD-style license in its `license.txt`. Check their notices and all transitive package licenses before external distribution.
- pypdf: BSD-3-Clause. pypdfium2: BSD-3-Clause / Apache-2.0 plus dependency licenses. Confirm bundled PDFium notices. Check remaining transitive dependencies before release.
- Do not bundle PyMuPDF in the product package; it uses AGPL-3.0 or a commercial license.
- Disclose the online model provider, page data sent, provider retention policy, and contact/consent process to trial users. The service implementation itself does not persist uploaded images.
- Use only scores the trial participants are authorized to process and upload. Provide an offline-only path for sensitive scores.

## Pilot validation

- Invite 10–15 orchestra librarians with real authorized scores and record conversion success, time to delivery, repeat use, and issues found by humans.
- Compare the same score batch with their current MuseScore/manual workflow. Decide whether to expand only after the delivery-time and quality improvements are observed.
