# AI 谱务助手 / Score Parts Assistant

A Windows-first desktop workflow for orchestra librarians: import partwise MusicXML scores, generate individual A4 PDF parts, review local quality findings, and prepare a delivery bundle. The conversion engine also remains available as a command-line tool.

**Supported input:** `.mxl`, `.musicxml`, `.xml` partwise MusicXML. MIDI transcription and PDF score recognition are outside this release.

输入须为 partwise 格式的 MusicXML。MXL 优先读取 `META-INF/container.xml` 指定的总谱；每个 `score-part` 生成一份分谱。原总谱的分页与换行会在分谱中重新排版，音符、休止符、力度和奏法等记谱内容保留在所选声部中。排练或出版前请人工核对分谱，尤其是翻页位置。安装与命令说明见下文。

## Install and start

Python 3.10 or newer is required. For a source checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.\.venv\Scripts\score-parts-desktop.exe
```

The desktop app supports file and folder drop, part selection, an A4 engraving scale, filename templates (`{title}`, `{part}`, `{id}`), saved presets, page preview, review findings, and confirmed delivery packaging. Each run creates a new `batch-...` directory, so older results are not silently overwritten.

The batch directory contains one folder per score, individual part PDFs, `manifest.json`, and `report.html`. After a human confirms review, the app creates `delivery.zip`. Unresolved findings remain visible in the report and bundle.

## Command-line tools

The original command is unchanged:

```powershell
score-parts "quartet.mxl" -o parts
score-parts "quartet.mxl" --list-parts
score-parts "quartet.mxl" --part "Violin I" --scale 70 --overwrite
```

The new batch command accepts multiple files or directories and writes a report:

```powershell
score-parts-batch "scores" "extra-score.mxl" -o "deliveries" --filename-pattern "{title} - {part}"
```

Errors are recorded per score; one bad file does not stop the remaining batch. The original score files are not copied into the delivery folder.

## Quality checks and review limits

Local checks confirm selected part and measure counts, exact preservation of each source measure's content during extraction, PDF readability and page count, A4 size, visible blank pages, title and part label, edge ink, sparse last pages, and potentially awkward page turns. These checks do **not** establish that the original score is musically correct or that every page turn is playable. Final review is required.

An optional online AI review considers **only a page the user selects and explicitly approves**. The client sends a rendered PNG plus title, part name, and page number; it does not send the MXL file or full PDF. Suggestions are marked as AI findings and cannot edit the score. The trial server stores quota counts but no page images. The model provider processes uploaded pages under its own terms; operators must disclose the provider and retention policy before issuing trial access.

To use online review, enter the HTTPS trial service URL and an issued token in the desktop app. The app does not save the token. Offline generation and quality checks work without an account, token, or network access.

## Trial service (operator setup)

The service is optional and is intended to be deployed behind HTTPS. Install `.[service]` and set these environment variables on the **server only**:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Model provider credential; never put it in the desktop app. |
| `OPENAI_MODEL` | A vision-capable Responses API model chosen by the operator. |
| `SCORE_PARTS_TRIAL_TOKENS` | Comma-separated invite tokens. Use long, random values. |
| `SCORE_PARTS_TRIAL_LIMIT` | Maximum pages per token; default 30. |
| `SCORE_PARTS_USAGE_DB` | Persistent SQLite quota database path. |

Start with `uvicorn score_parts.ai_service:app --host 127.0.0.1 --port 8000` for local testing. In public deployment, place it behind HTTPS, protect environment secrets, persist the quota database, disable request-body logging, and provision unique tokens for invited users. No public service URL or trial tokens are included in this repository.

## Windows package

Run `powershell -ExecutionPolicy Bypass -File .\build_windows.ps1` on Windows. It builds a portable `dist/ScorePartsAssistant-Windows.zip` and runs a packaged self-test. A fresh Windows machine still needs a separate installation and sample-score check before a public beta. The ZIP is a portable distribution, not a signed installer.

## Development

```powershell
python -m pip install -e ".[desktop,service,build]"
python -m unittest discover -s tests -v
```

See [release checks](RELEASE_CHECKLIST.md) for the remaining trial launch gates and third-party license notes. Source scores and generated parts are intentionally excluded from the repository.
