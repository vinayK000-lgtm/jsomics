# JSOMICS — Multi-Omics Research Intelligence Platform

**Live:** https://jsomics.com

AI-powered biomedical research platform combining GEO mRNA-seq DEG analysis,
PubMed literature mining, and GPT-4o-mini interpretation into one unified workflow.

## What makes JSOMICS different

Most tools are siloed — you run DESeq2 separately, search PubMed separately,
and manually reconcile the results. JSOMICS runs both in parallel and
cross-references them automatically, surfacing genes confirmed by both
expression data AND published literature as HIGH CONFIDENCE targets.

## Architecture## Core user workflow

1. Enter a GEO accession (e.g. GSE12345) or search by disease keyword
2. Select case vs control sample groups (or auto-detect)
3. Platform runs DEG analysis + PubMed search in parallel
4. Cross-reference engine finds genes in both tracks → HIGH CONFIDENCE targets
5. GPT-4o-mini interprets results and suggests follow-up analyses
6. Export gene list, pathway enrichment, and full report

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

## Environment variables (Vercel)## Local development

```bash
pip install -e ".[storage,dev]"
cp .env.example .env
# fill in .env values
uvicorn jsomics_api.main:app --reload --port 8000
```

## Tech stack

FastAPI · Supabase · Vercel · Supabase Auth · GitHub OAuth ·
NCBI E-utilities · KEGG REST API · GEO FTP · GPT-4o-mini ·
scipy · statsmodels · pandas · numpy
