-- JSOMICS — Complete Supabase Schema
-- Run in: Supabase → SQL Editor

create extension if not exists vector;

-- Evidence records (bio_research_ai core table)
create table if not exists public.evidence_records (
    id          bigserial primary key,
    dataset     text not null,
    record_id   text not null,
    disease     text,
    title       text not null,
    text        text not null,
    source_url  text,
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique(dataset, record_id)
);

create index if not exists evidence_records_lookup_idx
    on public.evidence_records(dataset, disease, title);

-- User profiles
create table if not exists public.profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    full_name   text,
    plan        text not null default 'free' check (plan in ('free', 'researcher', 'lab')),
    api_key     text unique default 'jsom_' || encode(gen_random_bytes(24), 'hex'),
    created_at  timestamptz default now()
);

-- Query log (rate limiting + analytics)
create table if not exists public.query_log (
    id           bigserial primary key,
    user_id      uuid references public.profiles(id),
    query        text not null,
    modalities   text[],
    result_count int,
    created_at   timestamptz default now()
);

-- RLS
alter table public.evidence_records enable row level security;
alter table public.profiles         enable row level security;
alter table public.query_log        enable row level security;

create policy "Service role manages evidence" on public.evidence_records for all
    using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "Authenticated read evidence" on public.evidence_records for select
    using (auth.role() = 'authenticated');
create policy "Users view own profile" on public.profiles for select
    using (auth.uid() = id);
create policy "Users update own profile" on public.profiles for update
    using (auth.uid() = id);
create policy "Users view own query log" on public.query_log for select
    using (auth.uid() = user_id);
create policy "Service role manages query log" on public.query_log for all
    using (auth.role() = 'service_role') with check (auth.role() = 'service_role');

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
    insert into public.profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name')
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

create index if not exists query_log_user_date_idx
    on public.query_log(user_id, created_at desc);

-- User settings (LLM provider preference, NCBI email, etc.)
create table if not exists public.user_settings (
    user_id      uuid primary key references public.profiles(id) on delete cascade,
    llm_provider text not null default 'openai' check (llm_provider in ('openai', 'anthropic')),
    ncbi_email   text,
    search_depth text not null default 'quick' check (search_depth in ('quick', 'deep', 'systematic')),
    default_omics text[] not null default array['literature', 'biomarkers', 'pathways', 'drug_targets'],
    preferences  jsonb not null default '{}'::jsonb,
    updated_at   timestamptz default now()
);

alter table public.user_settings enable row level security;

create policy "Users manage own settings" on public.user_settings for all
    using (auth.uid() = user_id) with check (auth.uid() = user_id);
