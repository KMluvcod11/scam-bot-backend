-- Run once in Supabase SQL Editor before deploying the sender-aware bot.
alter table public.detection_logs
  add column if not exists sender_user_id text,
  add column if not exists sender_display_name text;

create index if not exists detection_logs_sender_user_id_idx
  on public.detection_logs (sender_user_id)
  where sender_user_id is not null;
