begin;

alter extension vector set schema extensions;

alter function public.match_scam(
  extensions.vector, double precision, integer
)
  set search_path = pg_catalog, public, extensions, pg_temp;

alter function public.match_scam_samples(
  extensions.vector, double precision, integer
)
  set search_path = pg_catalog, public, extensions, pg_temp;

  notify pgrst, 'reload schema';

commit;