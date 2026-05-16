from __future__ import annotations

import urllib.parse
import urllib.request
from dataclasses import dataclass

from bio_research_ai.models import IngestionRecord


KEGG_BASE_URL = "https://rest.kegg.jp"


@dataclass(frozen=True)
class KeggPathway:
    pathway_id: str
    name: str
    organism: str = "hsa"
    raw: str | None = None

    @property
    def url(self) -> str:
        return f"https://www.kegg.jp/entry/{self.pathway_id}"

    def to_record(self, disease: str | None = None) -> IngestionRecord:
        text = self.raw or self.name
        return IngestionRecord(
            dataset="kegg",
            record_id=self.pathway_id,
            disease=disease,
            title=self.name,
            text=text,
            source_url=self.url,
            metadata={"organism": self.organism},
        )


class KeggClient:
    """Minimal KEGG REST client for pathway lookup."""

    def __init__(self, base_url: str = KEGG_BASE_URL, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def ingest(self, query: str, disease: str | None = None, limit: int = 25) -> list[IngestionRecord]:
        pathways = self.find_pathways(query=query, limit=limit)
        detailed = [self.get_pathway(pathway.pathway_id) or pathway for pathway in pathways]
        return [pathway.to_record(disease=disease) for pathway in detailed]

    def list_pathways(self, organism: str = "hsa") -> list[KeggPathway]:
        text = self._get_text(f"/list/pathway/{organism}")
        return parse_kegg_pathway_list(text, organism=organism)

    def find_pathways(self, query: str, organism: str = "hsa", limit: int = 25) -> list[KeggPathway]:
        encoded_query = urllib.parse.quote(query)
        text = self._get_text(f"/find/pathway/{encoded_query}")
        pathways = parse_kegg_pathway_list(text, organism=organism)
        organism_prefix = f"path:{organism}"
        filtered = [
            pathway for pathway in pathways if pathway.pathway_id.startswith(organism_prefix)
        ]
        return filtered[:limit]

    def get_pathway(self, pathway_id: str) -> KeggPathway | None:
        text = self._get_text(f"/get/{urllib.parse.quote(pathway_id)}")
        name = parse_kegg_name(text)
        if not name:
            return None
        organism = pathway_id.replace("path:", "")[:3]
        return KeggPathway(pathway_id=pathway_id, name=name, organism=organism, raw=text)

    def _get_text(self, path: str) -> str:
        url = f"{self.base_url}{path}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8")


def parse_kegg_pathway_list(text: str, organism: str = "hsa") -> list[KeggPathway]:
    pathways: list[KeggPathway] = []
    for line in text.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        pathway_id, name = line.split("\t", 1)
        pathways.append(KeggPathway(pathway_id=pathway_id.strip(), name=name.strip(), organism=organism))
    return pathways


def parse_kegg_name(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("NAME"):
            return line.replace("NAME", "", 1).strip()
    return None
