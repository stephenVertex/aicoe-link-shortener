-- Add last_synced_at to links table to track when each article was last synced
-- from the Substack RSS/sitemap feed via sync-substack edge function.
ALTER TABLE links ADD COLUMN IF NOT EXISTS last_synced_at timestamptz;
