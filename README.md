# JSOMICS — Multi-Omics Research Intelligence Platform

**Live:** https://jsomics.com

AI-powered biomedical research platform combining GEO mRNA-seq DEG analysis,
PubMed literature mining, and GPT-4o-mini interpretation into one unified workflow.

## What makes JSOMICS different

Most research tools are siloed. You run DESeq2 separately, search PubMed
separately, and manually reconcile the results. JSOMICS runs both in parallel
and cross-references them automatically — genes confirmed by both expression
data AND published literature are surfaced as HIGH CONFIDENCE targets.

## Architecture## Core user workflow

1. Enter a GEO accession (e.g. GSE12345) or search by disease keyword
2. Platform auto-detects case vs control sample groups
3. DEG analysis (t-test + BH correction) runs in parallel with PubMed search
4. Cross-reference engine finds genes confirmed in both tracks
5. GPT-4o-mini interprets findings and suggests follow-up analyses

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /v1/auth/signup | Create account |
| POST | /v1/auth/signin | Sign in, get JWT |
| GET  | /v1/auth/me | Current user |
| GET  | /v1/users/me | Profile + usage stats |
| GET  | /v1/users/me/history | Query history |
| POST | /v1/research | Multi-agent literature research |
| POST | /v1/geo/search | Search GEO datasets by keyword |
| GET  | /v1/geo/fetch | Fetch GEO dataset + sample list |
| POST | /v1/geo/analyse | Full DEG + literature + AI analysis |
| POST | /v1/ingest/pubmed | Fetch PubMed articles (paid plans) |
| GET  | /v1/ingest/status | Evidence store record count |
| GET  | /health | Liveness probe |
| GET  | /ready | Readiness + DB check |

## Plans

| Plan | Queries/day |
|------|-------------|
| free | 100 |
| researcher | 10,000 |
| lab | unlimited |

## Environment variables (set in Vercel dashboard)

| Variable | Description |
|----------|-------------|
| SUPABASE_URL | https://ajfxbmnzfrrlvzjozygt.supabase.co |
| SUPABASE_ANON_KEY | Supabase public anon key |
| SUPABASE_SERVICE_ROLE_KEY | Supabase service role key (secret) |
| SUPABASE_JWT_SECRET | JWT signing secret |
| SUPABASE_DATABASE_URL | Postgres connection URI (session pooler) |
| NCBI_EMAIL | Email for NCBI rate limit compliance |
| OPENAI_API_KEY | GPT-4o-mini for AI interpretation |
| ENV | production |
| KV_REST_API_URL | Upstash Redis URL (optional, for persistent cache) |
| KV_REST_API_TOKEN | Upstash Redis token (optional) |

## Local development

```bash
pip install -e ".[storage,dev]"
cp .env.example .env
# fill in .env values
uvicorn jsomics_api.main:app --reload --port 8000
```

## Tech stack

FastAPI · Supabase · Vercel · GitHub OAuth · NCBI E-utilities ·
KEGG REST API · PubChem REST API · GEO FTP · GPT-4o-mini ·
scipy · statsmodels · pandas · numpy · httpx
