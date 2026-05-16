from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from bio_research_ai.models import IngestionRecord


NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass(frozen=True)
class PubMedArticle:
    pmid: str
    title: str
    abstract: str
    journal: str | None = None
    year: int | None = None

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    def to_record(self, disease: str | None = None) -> IngestionRecord:
        metadata: dict[str, str | int | float | bool | None] = {}
        if self.journal:
            metadata["journal"] = self.journal
        if self.year:
            metadata["year"] = self.year
        return IngestionRecord(
            dataset="pubmed",
            record_id=f"PMID:{self.pmid}",
            disease=disease,
            title=self.title,
            text=self.abstract,
            source_url=self.url,
            metadata=metadata,
        )


class PubMedClient:
    """Small NCBI E-utilities client for PubMed search and abstract fetch."""

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        tool: str = "bio-research-ai",
        base_url: str = NCBI_EUTILS_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def ingest(self, query: str, disease: str | None = None, limit: int = 25) -> list[IngestionRecord]:
        pmids = self.search(query=query, retmax=limit)
        articles = self.fetch_abstracts(pmids)
        return [article.to_record(disease=disease) for article in articles]

    def search(self, query: str, retmax: int = 25) -> list[str]:
        params = self._base_params(
            db="pubmed",
            term=query,
            retmode="json",
            retmax=str(retmax),
            sort="relevance",
        )
        url = f"{self.base_url}/esearch.fcgi?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return list(payload.get("esearchresult", {}).get("idlist", []))

    def fetch_abstracts(self, pmids: list[str]) -> list[PubMedArticle]:
        if not pmids:
            return []
        params = self._base_params(
            db="pubmed",
            id=",".join(pmids),
            retmode="xml",
            rettype="abstract",
        )
        url = f"{self.base_url}/efetch.fcgi?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            xml_text = response.read().decode("utf-8")
        return parse_pubmed_xml(xml_text)

    def _base_params(self, **params: str) -> dict[str, str]:
        merged = {"tool": self.tool, **params}
        if self.email:
            merged["email"] = self.email
        if self.api_key:
            merged["api_key"] = self.api_key
        return merged


def parse_pubmed_xml(xml_text: str) -> list[PubMedArticle]:
    root = ET.fromstring(xml_text)
    articles: list[PubMedArticle] = []
    for article_node in root.findall(".//PubmedArticle"):
        pmid = _text(article_node, ".//PMID")
        if not pmid:
            continue

        title = _join_text(article_node, ".//ArticleTitle") or "Untitled PubMed article"
        abstract_parts = [
            "".join(part.itertext()).strip()
            for part in article_node.findall(".//Abstract/AbstractText")
        ]
        abstract = normalize_whitespace(" ".join(part for part in abstract_parts if part))
        journal = _join_text(article_node, ".//Journal/Title")
        year = _extract_year(article_node)

        articles.append(
            PubMedArticle(
                pmid=pmid,
                title=normalize_whitespace(title),
                abstract=abstract,
                journal=normalize_whitespace(journal) if journal else None,
                year=year,
            )
        )
    return articles


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _text(node: ET.Element, path: str) -> str | None:
    child = node.find(path)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _join_text(node: ET.Element, path: str) -> str | None:
    child = node.find(path)
    if child is None:
        return None
    return "".join(child.itertext()).strip()


def _extract_year(article_node: ET.Element) -> int | None:
    for path in (
        ".//ArticleDate/Year",
        ".//JournalIssue/PubDate/Year",
        ".//PubMedPubDate[@PubStatus='pubmed']/Year",
    ):
        value = _text(article_node, path)
        if value and value.isdigit():
            return int(value)
    medline_date = _text(article_node, ".//JournalIssue/PubDate/MedlineDate")
    if not medline_date:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", medline_date)
    return int(match.group(0)) if match else None
