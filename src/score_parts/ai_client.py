"""Explicitly opted-in page review client."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .batch import read_manifest, save_manifest
from .quality import render_page_png


def review_page(batch_dir: Path, relative_pdf: str, page: int, *, endpoint: str,
                trial_token: str, consent: bool) -> list[dict]:
    if not consent:
        raise ValueError("必须先明确同意上传所选页面")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("在线 AI 地址必须使用 HTTPS")
    if not trial_token.strip():
        raise ValueError("需要试用令牌")
    manifest = read_manifest(batch_dir)
    target = None
    for score in manifest["scores"]:
        for part in score["outputs"]:
            if part["file"] == relative_pdf:
                target = (score, part)
                break
    if target is None:
        raise ValueError("所选 PDF 不在当前批次中")
    score, part = target
    pdf_path = (batch_dir / relative_pdf).resolve()
    if not pdf_path.is_relative_to(batch_dir.resolve()):
        raise ValueError("所选 PDF 路径无效")
    image = render_page_png(pdf_path, page)
    body = json.dumps({
        "title": score["title"],
        "part": part["name"],
        "page": page,
        "image_base64": base64.b64encode(image).decode("ascii"),
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/check-page", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {trial_token.strip()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"在线 AI 服务返回 HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接在线 AI 服务：{error.reason}") from error
    if not isinstance(result, dict) or not isinstance(result.get("findings"), list):
        raise RuntimeError("在线 AI 返回格式无效")
    findings = []
    for item in result["findings"]:
        if not isinstance(item, dict):
            continue
        findings.append({
            "code": str(item.get("code", "ai_review"))[:80],
            "severity": "review" if item.get("severity") not in {"warning", "review"} else item["severity"],
            "message": str(item.get("message", "请人工检查"))[:500],
            "page": page,
            "evidence": str(item.get("evidence", ""))[:500],
            "source": "ai",
            "resolved": False,
        })
    part["findings"].extend(findings)
    manifest["ai_findings"].append({"file": relative_pdf, "page": page, "count": len(findings)})
    save_manifest(batch_dir, manifest)
    return findings
