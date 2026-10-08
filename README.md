# score-parts-cli

Export one A4 PDF per instrument from a partwise MusicXML score (`.mxl`, `.musicxml`, or `.xml`). The tool extracts each instrument, lays it out afresh with [Verovio](https://www.verovio.org/), and adds a title and page numbers. It does not transcribe MIDI or recognize notes in a PDF.

## Install

Requires Python 3.10 or newer. In a virtual environment:

```sh
python -m pip install "git+https://github.com/Cedarrr1/score-parts-cli.git"
```

For a local checkout, use `python -m pip install .` from this directory.

On Windows, CairoSVG may also require a working Cairo native library. If installation succeeds but PDF generation reports that Cairo cannot be loaded, install a Cairo runtime and make its DLL directory available on `PATH`.

## Use

```sh
score-parts "quartet.mxl" -o "parts"
score-parts "quartet.musicxml" --list-parts
score-parts "quartet.mxl" --part "Violin I" --part "Viola" -o "parts"
score-parts "quartet.mxl" --title "Danse Macabre" --scale 70 --overwrite
```

The command writes separate PDFs such as `Danse Macabre - Violin I.pdf`. It refuses to replace existing PDFs unless `--overwrite` is given. Use `score-parts --help` for all options.

## Input and output

- Input must be **partwise MusicXML**. An MXL archive is read through its `META-INF/container.xml` entry when present.
- Each `score-part` becomes a PDF. `--part` accepts a part name or ID and may be repeated.
- The title comes from the MusicXML work title, movement title, or first credit. Use `--title` to override it.
- Original full-score page and system breaks are removed so each part can be laid out on A4 pages. Original notes, rests, dynamics, articulations, and other MusicXML notation stay in the selected part.
- Page layout is automatic. Review the PDFs before rehearsal or publication, especially page turns and imported notation.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests
```

This repository contains the conversion tool only. It does not include source scores, generated PDFs, or bundled dependencies.
