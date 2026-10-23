# LINE group member counts

`get_group_member_count(group_id)` in `messaging.py` fetches the current
count from LINE. The count excludes the bot. Invalid responses and API
errors return `None`; zero is a valid count.

`save_group_join(event)` in `detection_history.py` retains the existing
group registration and name lookup, then calls `save_group_members(event)`.
Member join and leave webhooks also call `save_group_members(event)` through
the existing worker pool and event guard. The function uses the existing
history client and upserts only the count and last seen time, preserving
the group's name, join time and active status. Database failures return
`False` and do not interrupt message detection.

The existing `supabase/dashboard_schema.sql` already defines nullable
`line_sources.member_count`; no new migration is needed for that schema.
The live dashboard already reads this column.

Deploy and restart the bot to activate the handlers. Existing groups get
counts on the next member change or bot join; deployment does not backfill
them. Failed updates are not automatically retried. Duplicate delivery is
suppressed within the existing process-local event guard retention window.
LINE and database integration still needs to be verified in the deployed
environment; automated tests mock both services.
