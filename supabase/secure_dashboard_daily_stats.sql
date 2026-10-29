begin;

alter view public.dashboard_daily_stats
  set (security_invoker = true);

revoke all privileges on table public.dashboard_daily_stats
  from anon, authenticated;

grant select on table public.dashboard_daily_stats
  to authenticated;

commit;