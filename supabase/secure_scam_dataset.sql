-- ชุดตัวอย่างยังอ่านได้ด้วย publishable key ของบอต; เขียนผ่าน service_role ฝั่งเซิร์ฟเวอร์
-- รันทั้งไฟล์ด้วยเจ้าของตาราง เพื่อให้เปลี่ยนสิทธิ์และ policy พร้อมกัน
begin;

alter table public.scam_dataset enable row level security;

revoke insert, update, delete, truncate, references, trigger
  on table public.scam_dataset from anon, authenticated;
grant select on table public.scam_dataset to anon, authenticated;

drop policy if exists scam_dataset_read_only on public.scam_dataset;
create policy scam_dataset_read_only
  on public.scam_dataset
  for select
  to anon, authenticated
  using (true);

-- ตรวจสิทธิ์ที่ใช้ได้จริง รวมสิทธิ์ที่อาจรับต่อจาก role อื่น; ถ้ายังเขียนได้ให้ rollback
do $check$
declare
  checked_role text;
begin
  foreach checked_role in array array['anon', 'authenticated'] loop
    if not has_table_privilege(checked_role, 'public.scam_dataset', 'SELECT') then
      raise exception '% must retain read access to scam_dataset', checked_role;
    end if;

    if has_table_privilege(
      checked_role, 'public.scam_dataset',
      'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
    ) or has_any_column_privilege(
      checked_role, 'public.scam_dataset', 'INSERT, UPDATE, REFERENCES'
    ) then
      raise exception '% must not have write access to scam_dataset', checked_role;
    end if;
  end loop;
end
$check$;

commit;
