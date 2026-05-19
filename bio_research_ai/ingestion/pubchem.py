from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from bio_research_ai.models import IngestionRecord


PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


@dataclass(frozen=True)
class PubChemCompound:
    cid: str
    name: str
    molecular_formula: str | None = None
    molecular_weight: str | None = None
    canonical_smiles: str | None = None
    synonyms: list[str] | None = None

    @property
    def url(self) -> str:
        return f"https://pubchem.ncbi.nlm.nih.gov/compound/{self.cid}"

    def to_record(self, disease: str | None = None) -> IngestionRecord:
        parts = [f"PubChem compound {self.name} (CID {self.cid})."]
        if self.molecular_formula:
            parts.append(f"Molecular formula: {self.molecular_formula}.")
        if self.molecular_weight:
            parts.append(f"Molecular weight: {self.molecular_weight}.")
        if self.canonical_smiles:
            parts.append(f"Canonical SMILES: {self.canonical_smiles}.")
        if self.synonyms:
            parts.append("Synonyms: " + ", ".join(self.synonyms[:20]) + ".")
        return IngestionRecord(
            dataset="pubchem",
            record_id=f"CID:{self.cid}",
            disease=disease,
            title=self.name,
            text=" ".join(parts),
            source_url=self.url,
            metadata={"cid": self.cid},
        )


class PubChemClient:
    """Small PubChem PUG REST client for temporary, query-time enrichment."""

    def __init__(self, base_url: str = PUBCHEM_BASE_URL, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def ingest(self, query: str, disease: str | None = None, limit: int = 5) -> list[IngestionRecord]:
        compounds = self.search_compounds(query=query, limit=limit)
        return [compound.to_record(disease=disease) for compound in compounds]

    def search_compounds(self, query: str, limit: int = 5) -> list[PubChemCompound]:
        cids = self._name_to_cids(query, limit=limit)
        compounds: list[PubChemCompound] = []
        for cid in cids:
            props = self._compound_properties(cid)
            synonyms = self._compound_synonyms(cid)
            name = (synonyms[0] if synonyms else props.get("Title") or f"CID {cid}")
            compounds.append(
                PubChemCompound(
                    cid=str(cid),
                    name=str(name),
                    molecular_formula=_clean(props.get("MolecularFormula")),
                    molecular_weight=_clean(props.get("MolecularWeight")),
                    canonical_smiles=_clean(props.get("CanonicalSMILES")),
                    synonyms=synonyms,
                )
            )
        return compounds

    def _name_to_cids(self, query: str, limit: int) -> list[str]:
        encoded = urllib.parse.quote(query.strip())
        url = f"{self.base_url}/compound/name/{encoded}/cids/JSON"
        try:
            payload = self._get_json(url)
        except Exception:
            return []
        cids = payload.get("IdentifierList", {}).get("CID", [])
        return [str(cid) for cid in cids[:limit]]

    def _compound_properties(self, cid: str) -> dict:
        props = "MolecularFormula,MolecularWeight,CanonicalSMILES,Title"
        url = f"{self.base_url}/compound/cid/{urllib.parse.quote(cid)}/property/{props}/JSON"
        try:
            payload = self._get_json(url)
            rows = payload.get("PropertyTable", {}).get("Properties", [])
            return rows[0] if rows else {}
        except Exception:
            return {}

    def _compound_synonyms(self, cid: str) -> list[str]:
        url = f"{self.base_url}/compound/cid/{urllib.parse.quote(cid)}/synonyms/JSON"
        try:
            payload = self._get_json(url)
            rows = payload.get("InformationList", {}).get("Information", [])
            synonyms = rows[0].get("Synonym", []) if rows else []
            return [str(item) for item in synonyms[:25]]
        except Exception:
            return []

    def _get_json(self, url: str) -> dict:
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
