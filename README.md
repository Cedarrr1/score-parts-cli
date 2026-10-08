# score-parts-cli

Export one A4 PDF per instrument from a partwise MusicXML score (`.mxl`, `.musicxml`, or `.xml`). The tool extracts each instrument, lays it out afresh with [Verovio](https://www.verovio.org/), and adds a title and page numbers. It does not transcribe MIDI or recognize notes in a PDF.
将 partwise 格式的 MusicXML 乐谱（.mxl、.musicxml 或 .xml）按乐器拆分为单独的 A4 PDF：每个乐器导出为一个 PDF，使用 Verovio 重新排版，并自动添加标题与页码。本工具不转写 MIDI，也不识别 PDF 中的音符。

## Install（安装）

Requires Python 3.10 or newer. In a virtual environment:
需要 Python 3.10 或更高版本。在虚拟环境中执行：

```sh
python -m pip install "git+https://github.com/Cedarrr1/score-parts-cli.git"
```

For a local checkout, use `python -m pip install .` from this directory.
本地克隆后，可在项目目录中运行 python -m pip install .。


On Windows, CairoSVG may also require a working Cairo native library. If installation succeeds but PDF generation reports that Cairo cannot be loaded, install a Cairo runtime and make its DLL directory available on `PATH`.
Windows 上 CairoSVG 可能还需要 Cairo 原生库。若安装成功但生成 PDF 时提示无法加载 Cairo，请安装 Cairo 运行时并将其 DLL 目录加入 PATH。

## Use（使用）

```sh
score-parts "quartet.mxl" -o "parts"
score-parts "quartet.musicxml" --list-parts
score-parts "quartet.mxl" --part "Violin I" --part "Viola" -o "parts"
score-parts "quartet.mxl" --title "Danse Macabre" --scale 70 --overwrite
```

The command writes separate PDFs such as `Danse Macabre - Violin I.pdf`. It refuses to replace existing PDFs unless `--overwrite` is given. Use `score-parts --help` for all options.
命令会生成类似 Danse Macabre - Violin I.pdf 的独立 PDF。除非指定 --overwrite，否则不会覆盖已有 PDF。使用 score-parts --help 查看全部选项。


## Input and output（输入与输出）

- Input must be **partwise MusicXML**. An MXL archive is read through its `META-INF/container.xml` entry when present.
  输入须为 partwise 格式的 MusicXML。若为 MXL 压缩包，会优先读取其中的 META-INF/container.xml。


- Each `score-part` becomes a PDF. `--part` accepts a part name or ID and may be repeated.
  每个 score-part 生成一个 PDF。--part 可接受声部名称或 ID，且可重复指定。

- The title comes from the MusicXML work title, movement title, or first credit. Use `--title` to override it.
  标题取自 MusicXML 的 work title、movement title 或首个 credit；可用 --title 覆盖。
  
- Original full-score page and system breaks are removed so each part can be laid out on A4 pages. Original notes, rests, dynamics, articulations, and other MusicXML notation stay in the selected part.
  原始总谱的分页与换行会被移除，以便每个声部在 A4 页面上重新排版。所选声部中的音符、休止符、力度、奏法及其他 MusicXML 记谱信息均会保留。

- Page layout is automatic. Review the PDFs before rehearsal or publication, especially page turns and imported notation.
  页面布局为自动生成。排练或出版前请先检查 PDF，尤其注意翻页与导入的记谱。

## Development（开发）

```sh
python -m pip install -e .
python -m unittest discover -s tests
```

This repository contains the conversion tool only. It does not include source scores, generated PDFs, or bundled dependencies.
本仓库仅包含转换工具，不包含源乐谱、生成的 PDF 或捆绑的依赖。
