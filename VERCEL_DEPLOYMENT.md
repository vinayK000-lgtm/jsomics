# JSOMICS Vercel-only deployment

This version runs both frontend and backend on Vercel:

- Frontend: `frontend/index.html`
- Backend: `api/index.py` -> `jsomics_api.main:app`
- Temporary evidence: Vercel KV / Upstash Redis REST cache
- Supabase: authentication, user plans, usage logs, and saved reports only
- Live evidence sources: PubMed, KEGG, PubChem
- Optional analysis: OpenAI GPT or Anthropic Claude

## 1. Important Vercel config change

The old `vercel.json` used `builds`, which made Vercel ignore dashboard Build & Development settings.
The new `vercel.json` uses `rewrites` instead.

Use these dashboard settings:

```text
Framework Preset: Other
Build Command: leave empty
Output Directory: leave empty or frontend
Install Command: pip install -r requirements.txt
```

## 2. Required Vercel environment variables

Minimum:

```env
ENV=production
PUBLIC_SITE_URL=https://jsomics.com
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_JWT_SECRET=...
NCBI_EMAIL=your@email.com
LIVE_EVIDENCE_ENABLED=true
```

Recommended temporary cache:

```env
KV_REST_API_URL=...
KV_REST_API_TOKEN=...
CACHE_TTL_SECONDS=86400
```

Or Upstash Redis:

```env
UPSTASH_REDIS_REST_URL=...
UPSTASH_REDIS_REST_TOKEN=...
```

Optional GPT:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Optional Claude:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

## 3. New research flow

```text
User query
  -> check temporary cache
  -> fetch PubMed / PubChem / KEGG live if cache miss
  -> create temporary in-memory evidence repository for this request
  -> run JSOMICS agents
  -> optionally ask GPT/Claude to interpret the evidence
  -> save final response in temporary Redis/KV cache
  -> return result to frontend
```

No PubMed/PubChem/KEGG evidence is written permanently to Supabase by default.

## 4. Notes

- PubChem is compound-centric, so gene-only queries may return no PubChem results.
- PubMed and KEGG are the main live sources for gene/disease queries.
- Vercel serverless has execution time limits. Keep `max_results` modest.
- For heavy ingestion or long batch jobs, a background worker would still be better, but this package is configured for Vercel-only operation.
