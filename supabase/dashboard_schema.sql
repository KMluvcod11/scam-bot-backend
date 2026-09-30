-- Scam Detection Bot dashboard schema
-- Run this once in Supabase Dashboard > SQL Editor.
-- The backend should use SUPABASE_SERVICE_ROLE_KEY only when inserting logs.

create extension if not exists pgcrypto;

create table if not exists public.dashboard_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

create table if not exists public.line_sources (
  id uuid primary key default gen_random_uuid(),
  line_source_id text not null unique,
  source_type text not null check (source_type in ('group', 'room', 'user')),
  display_name text,
  member_count integer check (member_count is null or member_count >= 0),
  bot_joined_at timestamptz,
  last_seen_at timestamptz not null default now(),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.detection_logs (
  id uuid primary key default gen_random_uuid(),
  line_event_id text not null unique,
  source_id uuid references public.line_sources(id) on delete set null,
  source_type text not null check (source_type in ('group', 'room', 'user')),
  message_text text not null,
  message_preview text not null,
  received_at timestamptz not null default now(),
  detection_status text not null check (detection_status in (
    'bypassed', 'conversation', 'no_risk_found', 'risk_found', 'uncertain', 'error'
  )),
  is_scam boolean,
  risk_level text check (risk_level is null or risk_level in ('low', 'medium', 'high')),
  reason text check (reason is null or char_length(reason) <= 500),
  decision_method text not null check (decision_method in ('bypass', 'vector', 'llm', 'fallback', 'unknown')),
  similarity_percent numeric(5,2) check (
    similarity_percent is null or (similarity_percent >= 0 and similarity_percent <= 100)
  ),
  matched_label text check (matched_label is null or matched_label in ('ham', 'spam')),
  has_trigger boolean,
  warning_attempted boolean not null default false,
  warning_sent boolean,
  error_stage text check (error_stage is null or error_stage in ('embedding', 'vector_db', 'llm', 'analysis', 'line_reply')),
  created_at timestamptz not null default now(),
  constraint detection_result_is_consistent check (
    (detection_status = 'error' and is_scam is null)
    or (detection_status <> 'error' and is_scam is not null)
  ),
  constraint warning_result_is_consistent check (
    (warning_attempted = false and warning_sent is null)
    or warning_attempted = true
  )
);

create index if not exists detection_logs_received_at_idx
  on public.detection_logs (received_at desc);
create index if not exists detection_logs_source_received_at_idx
  on public.detection_logs (source_id, received_at desc);
create index if not exists detection_logs_risk_received_at_idx
  on public.detection_logs (risk_level, received_at desc)
  where is_scam = true;
create index if not exists line_sources_active_last_seen_idx
  on public.line_sources (is_active, last_seen_at desc);

-- A compact source for the Overview cards and daily chart.
create or replace view public.dashboard_daily_stats as
select
  received_at::date as day,
  count(*) as total_messages,
  count(*) filter (where is_scam is true) as scam_messages,
  count(*) filter (where detection_status = 'error') as failed_checks,
  count(*) filter (where warning_sent is true) as warnings_sent,
  round(100.0 * count(*) filter (where is_scam is true) / nullif(count(*), 0), 2) as scam_rate_percent
from public.detection_logs
group by received_at::date;

-- Run the view with the caller's RLS permissions, not the view owner's.
alter view public.dashboard_daily_stats set (security_invoker = true);

-- Enables the dashboard only for signed-in users entered in dashboard_admins.
alter table public.dashboard_admins enable row level security;
alter table public.line_sources enable row level security;
alter table public.detection_logs enable row level security;

drop policy if exists "dashboard admins can read their access" on public.dashboard_admins;
create policy "dashboard admins can read their access"
  on public.dashboard_admins for select to authenticated
  using (user_id = auth.uid());

drop policy if exists "dashboard admins can read LINE sources" on public.line_sources;
create policy "dashboard admins can read LINE sources"
  on public.line_sources for select to authenticated
  using (exists (select 1 from public.dashboard_admins where user_id = auth.uid()));

drop policy if exists "dashboard admins can read detection logs" on public.detection_logs;
create policy "dashboard admins can read detection logs"
  on public.detection_logs for select to authenticated
  using (exists (select 1 from public.dashboard_admins where user_id = auth.uid()));

grant select on public.dashboard_daily_stats to authenticated;

-- After creating the first dashboard user's Supabase Auth account, grant access:
-- insert into public.dashboard_admins (user_id) values ('AUTH_USER_UUID_HERE');
