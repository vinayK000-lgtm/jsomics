from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from jsomics_api.main import app
from jsomics_api.routers.auth import _validate_redirect_to


def test_health_ready_and_auth_config_are_available():
    client = TestClient(app)

    health = client.get("/health")
    ready = client.get("/ready")
    config = client.get("/v1/auth/config")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["database"] in {"ok", "not_configured"}
    assert config.status_code == 200
    assert {"supabase_url", "supabase_anon_key", "redirect_base"} <= set(config.json())


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://jsomics.com/account/activated", True),
        ("http://localhost:3000/auth/callback", True),
        ("https://evil.example/auth/callback", False),
        ("http://jsomics.com/auth/callback", False),
        ("https://jsomics.com/#token", False),
        ("ftp://localhost/auth/callback", False),
    ],
)
def test_signup_redirect_validation(url: str, allowed: bool):
    if allowed:
        assert _validate_redirect_to(url) == url
    else:
        with pytest.raises(HTTPException):
            _validate_redirect_to(url)


def test_research_endpoint_accepts_api_key_and_inline_evidence(monkeypatch):
    monkeypatch.setenv("BIO_RESEARCH_API_KEYS", "test-key")
    payload = {
        "query": "EGFR biomarkers in lung cancer",
        "disease": "lung cancer",
        "mode": "biomarkers",
        "evidence_level": "medium",
        "max_results": 5,
        "inline_evidence": [
            {
                "source": "pubmed",
                "source_id": "PMID:test",
                "title": "EGFR in lung cancer",
                "text": "EGFR is elevated in lung cancer and linked to MAPK pathway activation.",
                "url": "https://pubmed.ncbi.nlm.nih.gov/",
                "quality": "medium",
            }
        ],
    }

    with TestClient(app) as client:
        response = client.post(
            "/v1/research",
            json=payload,
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == payload["query"]
    assert body["research_use_only"] is True
    assert body["provenance"]["from_cache"] is False
