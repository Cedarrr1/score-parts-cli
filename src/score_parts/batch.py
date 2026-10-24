"""Batch jobs, delivery manifests, reports, and review bundles."""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from .engine import _safe_name, convert, inspect_score
from .quality import check_pdf, finding


SUPPORTED = {".mxl", ".musicxml", ".xml"}


def collect_sources(paths: list[Path]) -> list[Path]:
    """Collect supported files recursively from folders, retaining explicit invalid files."""
    found: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidates = sorted((item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in SUPPORTED),
                            key=lambda item: item.name.casefold()) if path.is_dir() else [path]
        for candidate in candidates:
            key = str(candidate.resolve()).casefold()
            if key not in seen:
                found.append(candidate)
                seen.add(key)
    return found


def _new_batch_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("batch-%Y%m%d-%H%M%S")
    for version in range(1, 1000):
        candidate = root / (stem if version == 1 else f"{stem}-v{version}")
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("Unable to allocate a new batch directory")


def _write_manifest(batch_dir: Path, manifest: dict) -> None:
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _report(batch_dir: Path, manifest: dict) -> None:
    cards = []
    for score in manifest["scores"]:
        title = escape(score.get("title") or Path(score["source"]).name)
        status = escape(score["status"])
        if score["status"] == "failed":
            body = f'<p class="error">{escape(score.get("error", "未知错误"))}</p>'
        else:
            rows = []
            for part in score["outputs"]:
                rel = part["file"]
                link = quote(rel.replace("\\", "/"), safe="/")
                issues = "".join(
                    f'<li class="{escape(item["severity"])}">'
                    f'{"AI 建议" if item["source"] == "ai" else "程序检查"} · {escape(item["severity"])} · '
                    f'{"第 " + str(item["page"]) + " 页 · " if item["page"] else ""}'
                    f'{escape(item["message"])}'
                    f'{"（" + escape(item["evidence"]) + "）" if item["evidence"] else ""}'
                    f'{" · 已处理" if item["resolved"] else ""}</li>'
                    for item in part["findings"]
                ) or '<li class="ok">未发现程序可检测的问题</li>'
                rows.append(
                    f'<section class="part"><h3><a href="{link}">{escape(part["name"])}</a>'
                    f' <small>{part["pages"]} 页 · {part["expected_measures"]} 小节</small></h3>'
                    f'<ul>{issues}</ul></section>'
                )
            body = "".join(rows)
        cards.append(f'<article><h2>{title} <small>{status}</small></h2><p class="source">{escape(score["source"])}</p>{body}</article>')
    review = "已确认人工审阅" if manifest.get("reviewed") else "尚未确认人工审阅"
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AI 谱务助手 · 交付报告</title>
<style>body{{font:16px/1.55 "Segoe UI",sans-serif;color:#243044;background:#f5f6f8;margin:0 auto;max-width:1050px;padding:32px}}
h1{{font-size:28px}}article{{background:white;border:1px solid #dce0e5;border-radius:12px;margin:18px 0;padding:20px 24px}}
h2{{margin:0;font-size:21px}}h3{{margin:14px 0 4px}}small,.source{{color:#637083;font-size:13px}}
.part{{border-top:1px solid #e8ebef}}ul{{margin:4px 0 12px}}li{{padding:2px 0}}
.error,.warning{{color:#ad3730}}.review{{color:#91630c}}.ok{{color:#267849}}a{{color:#175ea9}}</style>
<h1>分谱交付报告</h1><p>{escape(review)} · {escape(manifest["created_at"])} · 共 {len(manifest["scores"])} 份总谱 · 在线 AI 检查 {len(manifest["ai_findings"])} 页</p>
<p>“程序检查通过”不等于乐谱已经人工校对。AI 建议只是疑点，需结合原谱判断。</p>{''.join(cards)}</html>'''
    (batch_dir / "report.html").write_text(html, encoding="utf-8")


def run_batch(paths: list[Path], output_root: Path, *, scale: int = 70,
              filename_pattern: str = "{title} - {part}",
              selected: dict[str, list[str]] | None = None, on_event=None) -> Path:
    sources = collect_sources(paths)
    if not sources:
        raise ValueError("没有找到 MXL 或 MusicXML 文件")
    batch_dir = _new_batch_dir(output_root)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reviewed": False,
        "scores": [],
        "ai_findings": [],
    }
    _write_manifest(batch_dir, manifest)
    for index, source in enumerate(sources, 1):
        score_dir = None
        record = {"source": source.name, "title": source.stem,
                  "status": "pending", "parts": [], "outputs": [], "error": None}
        manifest["scores"].append(record)
        if on_event:
            on_event(index, len(sources), f"正在处理 {source.name}")
        try:
            info = inspect_score(source)
            record["title"] = info["title"]
            record["parts"] = info["parts"]
            chosen = (selected or {}).get(str(source.resolve()))
            chosen_ids = set(chosen) if chosen is not None else {part["id"] for part in info["parts"]}
            if not chosen_ids:
                raise ValueError("没有选中声部")
            if not chosen_ids <= {part["id"] for part in info["parts"]}:
                raise ValueError("所选声部不在该总谱中")
            score_dir = batch_dir / f"{index:03d} {_safe_name(info['title'])}"
            results = convert(source, score_dir, chosen_parts=sorted(chosen_ids), scale=scale,
                              filename_pattern=filename_pattern,
                              on_part=(lambda _id, name: on_event(index, len(sources), f"{source.name} · {name}")) if on_event else None)
            selected_parts = [part for part in info["parts"] if part["id"] in chosen_ids]
            if len(results) != len(selected_parts):
                raise RuntimeError("导出的 PDF 数量与所选声部数量不一致")
            for part_info, (name, pages, path) in zip(selected_parts, results):
                qc = check_pdf(path, info["title"], name, part_info["measures"])
                qc.update({"id": part_info["id"], "name": name, "file": path.relative_to(batch_dir).as_posix()})
                if qc["pages"] != pages:
                    qc["findings"].append(finding("page_count", "error", "导出页数与 PDF 页数不一致"))
                record["outputs"].append(qc)
            record["status"] = "completed"
        except Exception as error:
            record["status"] = "failed"
            record["error"] = f"{type(error).__name__}: {error}"
            if score_dir is not None and score_dir.exists() and score_dir.resolve().is_relative_to(batch_dir.resolve()):
                try:
                    shutil.rmtree(score_dir)
                except OSError as cleanup_error:
                    record["error"] += f"; failed to clean partial output: {cleanup_error}"
        _write_manifest(batch_dir, manifest)
        _report(batch_dir, manifest)
    return batch_dir


def read_manifest(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))


def save_manifest(batch_dir: Path, manifest: dict) -> None:
    _write_manifest(batch_dir, manifest)
    _report(batch_dir, manifest)


def make_bundle(batch_dir: Path, *, confirm_review: bool) -> Path:
    if not confirm_review:
        raise ValueError("请先确认已人工审阅报告")
    manifest = read_manifest(batch_dir)
    manifest["reviewed"] = True
    save_manifest(batch_dir, manifest)
    destination = batch_dir / "delivery.zip"
    for version in range(2, 1000):
        if not destination.exists():
            break
        destination = batch_dir / f"delivery-v{version}.zip"
    if destination.exists():
        raise RuntimeError("Unable to allocate a new delivery archive")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "report.html"):
            archive.write(batch_dir / name, name)
        for score in manifest["scores"]:
            for part in score["outputs"]:
                relative = Path(part["file"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("报告包含不安全的文件路径")
                archive.write(batch_dir / relative, relative.as_posix())
    return destination
