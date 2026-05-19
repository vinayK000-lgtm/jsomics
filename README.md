# JSOMICS

JSOMICS is a FastAPI-backed multi-omics research intelligence platform for
biomarker discovery, pathway analysis, literature mining, and drug target
prioritization.

This project is for biomedical research assistance. It is not a clinical
diagnosis, treatment, or medical decision product.

## Current Features

- Supabase-backed email/password authentication.
- GitHub OAuth support through Supabase Auth.
- Email verification and password recovery redirect flow.
- Authenticated research API with Supabase JWT or `X-API-Key`.
- Per-user daily rate limits by plan.
- PubMed and KEGG ingestion endpoints for researcher/lab plans.
- Evidence-grounded multi-agent research responses with provenance.
- Optional Supabase query cache for repeated research requests.
- Local development fallback with in-memory or SQLite evidence storage.
- Backend smoke tests for health, auth config, redirect safety, and research.

## Project Layout

```text
bio_research_ai/        Core research agents, ingestion clients, models, storage
jsomics_api/            Production FastAPI app, auth, users, research, ingest
frontend/               Static browser app copy
index.html              Static browser app entry
docs/                   Deployment and product documentation
gpt/                    Custom GPT action package
scripts/                Data ingestion helpers
tests/                  Backend smoke tests
```

## Requirements

- Python 3.11 or newer.
- Supabase project for login and Postgres-backed production use.
- Optional NCBI email/API key for PubMed ingestion.

The pinned Supabase client version avoids a newer optional native dependency
chain that can fail on this Windows/Python 3.14 setup.

## Local Setup

```powershell
cd C:\Users\vinay\jsomics
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For development and tests:

```powershell
python -m pip install -e ".[dev]"
```

## Environment Variables

Copy the sample file and fill in real values:

```powershell
Copy-Item .env.example .env
```

Minimum useful local values:

```dotenv
ENV=development
APP_NAME=JSOMICS
PUBLIC_SITE_URL=https://jsomics.com

SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret

BIO_RESEARCH_API_KEYS=local-dev-key
ALLOWED_ORIGINS=https://jsomics.com,http://localhost:3000,http://127.0.0.1:5500
```

The anon key is the public browser key from Supabase Project Settings > API.
Keep the service role key and JWT secret out of frontend code and GitHub.

## Run The Backend

```powershell
python -m uvicorn jsomics_api.main:app --reload --port 8000
```

Health checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8000/v1/auth/config
```

Open API docs in development:

```text
http://127.0.0.1:8000/api/docs
```

## Run Tests

```powershell
python -m pytest
python -m pip check
python -m compileall jsomics_api bio_research_ai api index.py
```

## Auth Setup

In Supabase Auth settings:

- Set Site URL to `https://jsomics.com`.
- Add redirect URLs for `https://jsomics.com`, local dev URLs, and your deployed API/frontend callback URL.
- Enable email confirmation for signup verification.
- Enable GitHub as an OAuth provider if you want social login.
- Google and Microsoft login are intentionally not enabled in the current UI.

The frontend reads Supabase browser configuration from:

```text
GET /v1/auth/config
```

## Example Research Request

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/research `
  -Method Post `
  -Headers @{ "X-API-Key" = "local-dev-key" } `
  -ContentType "application/json" `
  -Body '{
    "query": "EGFR biomarkers in lung cancer",
    "disease": "lung cancer",
    "mode": "biomarkers",
    "evidence_level": "medium",
    "max_results": 5,
    "inline_evidence": [
      {
        "source": "pubmed",
        "source_id": "PMID:example",
        "title": "EGFR in lung cancer",
        "text": "EGFR is elevated in lung cancer and linked to MAPK pathway activation.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/",
        "quality": "medium"
      }
    ]
  }'
```

Supported `mode` values:

- `auto`
- `literature`
- `biomarkers`
- `pathways`
- `drug_targets`

## Ingestion

PubMed and KEGG ingestion endpoints require authenticated users on the
`researcher` or `lab` plan.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/ingest/status `
  -Headers @{ "X-API-Key" = "local-dev-key" }
```

For NCBI production usage, configure:

```dotenv
NCBI_EMAIL=you@example.com
NCBI_API_KEY=optional-key
```

## Deployment Notes

Railway/Fly/Render start command:

```text
python -m uvicorn jsomics_api.main:app --host 0.0.0.0 --port $PORT
```

Production environment should include:

- `ENV=production`
- `PUBLIC_SITE_URL=https://jsomics.com`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_DATABASE_URL`
- `ALLOWED_ORIGINS=https://jsomics.com,https://www.jsomics.com`

## GitHub Pages

GitHub Pages can host the static frontend only. It cannot run the FastAPI
backend. Deploy the backend separately, then configure the static frontend to
talk to the deployed API.

## Product Docs

- [Architecture](docs/ARCHITECTURE.md)
- [API contract](docs/API_CONTRACT.md)
- [Commercialization plan](docs/COMMERCIALIZATION.md)
- [GitHub Pages launch](docs/GITHUB_PAGES.md)
- [Supabase + Railway deployment](docs/SUPABASE_RAILWAY.md)
- [Custom GPT package](gpt/README.md)

## Safety

Responses must include evidence, confidence, provenance, and research-use
limitations. Human expert review is required before operational or clinical use.
