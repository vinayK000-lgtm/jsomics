# JSOMICS

Evidence-grounded biomedical research agent platform for disease intelligence,
biomarker discovery, pathway analysis, literature mining, and drug target
prioritization.

The project is designed as a commercial research software foundation. It is not a
clinical diagnosis or treatment decision product.

## What is included

- PubMed ingestion client using NCBI E-utilities.
- KEGG pathway lookup client using KEGG REST.
- Evidence-first domain models for biomarkers, pathways, reports, and citations.
- In-memory vector search for local development, with a pgvector schema stub for production.
- Biomarker, pathway, literature mining, and drug target agents with a simple orchestrator.
- FastAPI endpoint with API-key auth, provenance, confidence labels, and research caveats.
- SQLite-backed persistent repository for pilot deployments.
- Docker and Compose deployment artifacts.
- Unit tests for XML parsing, marker extraction, literature triples, target scoring, vector search, and orchestration.

## Project layout

```text
bio_research_ai/
  agents/          Agent modules and orchestration
  api/             FastAPI schemas and app
  ingestion/       PubMed and KEGG clients
  models/          Domain dataclasses and enums
  storage/         Repository and vector search abstractions
scripts/
  ingest_pubmed_kegg.py
tests/
```

## Quick start

```powershell
cd C:\Users\vinay\Documents\Codex\2026-05-16\devoloping-an-to-do-ai-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn bio_research_ai.api.main:app --reload
```

If you already created a virtual environment in `C:\Users\vinay`, either keep using it after changing into this project directory, or create a fresh `.venv` inside the project as shown above.

## Test the API

Keep `uvicorn` running in the first PowerShell window. In a second PowerShell window, check the health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Open the interactive research console:

```text
http://127.0.0.1:8000/
```

For local authenticated runs, use `local-dev-key` when
`BIO_RESEARCH_API_KEYS=local-dev-key`.

Then call the research endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/research `
  -Method Post `
  -ContentType "application/json" `
  -Body '{
    "query": "What are early biomarkers and pathways in Parkinson disease?",
    "disease": "Parkinson disease",
    "mode": "biomarkers",
    "evidence_level": "medium",
    "inline_evidence": [
      {
        "source": "pubmed",
        "source_id": "PMID:example",
        "title": "SNCA and Parkinson disease",
        "text": "SNCA is elevated in Parkinson disease. LRRK2 is implicated. Mitochondrial dysfunction pathway is associated with disease progression.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/"
      }
    ]
  }'
```

You can also call the same endpoint from Python:

```python
import requests

response = requests.post(
    "http://127.0.0.1:8000/v1/research",
    json={
        "query": "What are early biomarkers and pathways in Parkinson's disease?",
        "disease": "Parkinson's disease",
        "mode": "biomarkers",
        "evidence_level": "medium",
        "inline_evidence": [
            {
                "source": "pubmed",
                "source_id": "PMID:example",
                "title": "Example biomarker study",
                "text": "SNCA and LRRK2 are associated with Parkinson's disease. Mitochondrial dysfunction pathway is implicated.",
                "url": "https://pubmed.ncbi.nlm.nih.gov/"
            }
        ]
    },
)
print(response.json())
```

Supported `mode` values:

- `auto`: route from query keywords.
- `literature`: extract findings and knowledge graph triples from evidence.
- `biomarkers`: rank candidate gene/protein markers and pathway context.
- `pathways`: extract dysregulated pathway mentions and KEGG-style records.
- `drug_targets`: run literature, biomarker, pathway, and drug target scoring.

The API response includes `biomarkers`, `pathways`, `literature_findings`,
`knowledge_graph_triples`, `drug_targets`, `cross_agent_insights`, and
`unified_references`.

## Ingest a small PubMed/KEGG dataset

```powershell
python scripts\ingest_pubmed_kegg.py --disease "Parkinson's disease" --retmax 20 --out data\parkinsons.jsonl
```

For NCBI production usage, set an email and optional API key:

```powershell
$env:NCBI_EMAIL = "you@example.com"
$env:NCBI_API_KEY = "optional-key"
```

To persist evidence in SQLite:

```powershell
python scripts\ingest_pubmed_kegg.py --disease "Parkinson's disease" --retmax 20 --sqlite data\research.sqlite
$env:BIO_RESEARCH_SQLITE_PATH = "data\research.sqlite"
$env:BIO_RESEARCH_API_KEYS = "local-dev-key"
uvicorn bio_research_ai.api.main:app --reload
```

Authenticated API calls use:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/research `
  -Method Post `
  -Headers @{ "X-API-Key" = "local-dev-key" } `
  -ContentType "application/json" `
  -Body '{"query":"EGFR drug targets","disease":"NSCLC","mode":"drug_targets"}'
```

## Docker

```powershell
$env:BIO_RESEARCH_API_KEYS = "change-me"
docker compose up --build
```

The container stores SQLite data in the `bio_research_data` Docker volume.

## Product Docs

- [Architecture](docs/ARCHITECTURE.md)
- [API contract](docs/API_CONTRACT.md)
- [Commercialization plan](docs/COMMERCIALIZATION.md)
- [Google free web launch](docs/GOOGLE_FREE_WEB.md)
- [GitHub Pages launch](docs/GITHUB_PAGES.md)
- [Supabase + Railway deployment](docs/SUPABASE_RAILWAY.md)
- [Custom GPT package](gpt/README.md)
- [ChatGPT Explore setup](gpt/chatgpt_explore_setup.md)

## Free GitHub Pages Web Launch

The `github-pages/` folder contains a static JSOMICS webpage that can be published
for free with GitHub Pages. It runs a browser-side demo and can later connect to a
hosted JSOMICS backend through the `Remote API URL` field.

GitHub Pages cannot run the FastAPI backend. Use it for the public webpage, then
host the API separately when you need live database-backed research or ChatGPT
Actions.

## Free Google Web Launch

Use Firebase Hosting for the actual static JSOMICS app:

```powershell
npm install -g firebase-tools
firebase login
Copy-Item .firebaserc.example .firebaserc
# edit .firebaserc with your Firebase project ID
firebase deploy --only hosting
```

Use Google Sites for a no-code wrapper page, then embed the Firebase URL.

## Supabase + Railway

Use Supabase for login and Postgres, then deploy the FastAPI backend to Railway:

```text
Supabase Auth + Supabase Postgres -> Railway FastAPI -> GitHub/Firebase static UI
```

See [Supabase + Railway deployment](docs/SUPABASE_RAILWAY.md).

## Next build steps

1. Replace the in-memory vector store with Postgres + pgvector.
2. Add PubMedBERT/BioBERT NER for genes, diseases, variants, and chemicals.
3. Add UniProt, ClinVar, OMIM, DrugBank, ChEMBL, Reactome, PDB, and STRING clients.
4. Add organization accounts, API-key management, usage metering, and audit logs.
5. Add expert review labels for instruction tuning and confidence calibration.
6. Add React disease explorer views for marker heatmaps, pathway networks, and exportable reports.

## Safety note

This platform is for biomedical research assistance, not clinical diagnosis. Production responses should always include evidence, confidence, provenance, and review status.
