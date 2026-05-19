# JSOMICS Ultimate Multiomics Architecture

This package upgrades JSOMICS from a single blocking literature search into a cache-first, job-based multiomics platform running on Vercel.

## What changed

- Added job lifecycle API:
  - `POST /v1/jobs` creates a multiomics job immediately.
  - `POST /v1/jobs/{job_id}/run` executes the source agents and LLM synthesis.
  - `GET /v1/jobs/{job_id}/status` returns live job status.
  - `POST /v1/jobs/{job_id}/stop` requests cancellation.
  - `GET /v1/jobs/{job_id}/result` returns a completed result.
- Added source-parallel live evidence fetching with per-source timeouts.
- Added temporary job/result state using Vercel KV / Upstash Redis, with memory fallback for local testing.
- Added frontend stop button, multiomics source selection, quick/deep/systematic depth, job status line, and LLM status badges.
- Kept Supabase for auth/users/plans/logs, not large temporary evidence storage.

## Environment variables

Required for auth:

```env
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
```

Recommended for cache/job state:

```env
KV_REST_API_URL=
KV_REST_API_TOKEN=
# or
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
CACHE_TTL_SECONDS=86400
JOB_TTL_SECONDS=3600
```

Recommended for external evidence:

```env
NCBI_EMAIL=your@email.com
NCBI_API_KEY=
SOURCE_TIMEOUT_SECONDS=10
```

For OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
```

For Claude:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

## Notes

The Stop button cancels the frontend request immediately and marks the backend job as cancelled. External API calls that have already started may run until their source-level timeout, but their output will not be used by the UI after cancellation.

For very long systematic multiomics workflows, keep source timeouts conservative on Vercel and use cache aggressively.
