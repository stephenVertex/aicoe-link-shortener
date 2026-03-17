-- Add last_synced_at column to track when article metadata was last verified from Substack
ALTER TABLE links ADD COLUMN IF NOT EXISTS last_synced_at timestamptz;
