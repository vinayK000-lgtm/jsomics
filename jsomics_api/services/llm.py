from __future__ import annotations

import json
import os
from typing import Any

import httpx

from bio_research_ai.models import IngestionRecord, ResearchReport

SYSTEM_PROMPT = """You are JSOMICS, a biomedical research analysis assistant.
Use only the evidence supplied by the backend from biomedical databases.
Do not invent PMIDs, citations, genes, pathways, compounds, drug targets, or claims.
Return cautious research-use analysis. Say clearly when evidence is weak or absent.
"""


def llm_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


def _provider() -> str:
    configured = os.getenv("LLM_PROVIDER", "").strip().lower()
    if configured in {"openai", "anthropic"}:
        return configured
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "openai"


def build_evidence_context(records: list[IngestionRecord], max_chars: int = 18000) -> str:
    chunks: list[str] = []
    total = 0
    for index, record in enumerate(records, start=1):
        year = record.metadata.get("year") if record.metadata else None
        block = f"""
[EVIDENCE {index}]
Source: {record.dataset}
ID: {record.record_id}
Title: {record.title}
Year: {year or "unknown"}
URL: {record.source_url or ""}
Text: {record.text[:2500]}
""".strip()
        if total + len(block) > max_chars:
            break
        chunks.append(block)
        total += len(block)
    return "\n\n".join(chunks)


def build_report_summary(report: ResearchReport) -> dict[str, Any]:
    return {
        "rule_based_answer": report.answer,
        "biomarkers": [item.name for item in report.biomarkers[:10]],
        "pathways": [item.name for item in report.pathways[:10]],
        "drug_targets": [item.gene for item in report.drug_targets[:10]],
        "literature_findings": [item.finding for item in report.literature_findings[:10]],
        "references": report.unified_references[:20],
    }


async def analyse_with_llm(query: str, disease: str | None, records: list[IngestionRecord], report: ResearchReport) -> dict[str, Any] | None:
    if not records or not llm_enabled():
        return None

    provider = _provider()
    payload = {
        "query": query,
        "disease": disease,
        "evidence_context": build_evidence_context(records),
        "current_structured_findings": build_report_summary(report),
        "output_schema": {
            "executive_summary": "string",
            "biomarker_interpretation": ["string"],
            "pathway_interpretation": ["string"],
            "drug_target_interpretation": ["string"],
            "literature_interpretation": ["string"],
            "limitations": ["string"],
            "confidence": "low|medium|high",
        },
    }
    prompt = "Analyse the following JSOMICS evidence and return valid JSON only:\n" + json.dumps(payload, ensure_ascii=False)

    if provider == "anthropic":
        return await _call_anthropic(prompt)
    return await _call_openai(prompt)


async def _call_openai(prompt: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        res = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    res.raise_for_status()
    data = res.json()
    text = data.get("output_text") or _extract_openai_text(data)
    return _json_or_text(text)


async def _call_anthropic(prompt: str) -> dict[str, Any] | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    body = {
        "model": model,
        "max_tokens": 2500,
        "temperature": 0.2,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=45) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
        )
    res.raise_for_status()
    data = res.json()
    text = "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
    return _json_or_text(text)


def _extract_openai_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(content.get("text", ""))
    return "\n".join(parts).strip()


def _json_or_text(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"executive_summary": text, "confidence": "unknown"}
