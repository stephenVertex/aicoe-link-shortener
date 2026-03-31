-- Add archiving support to aifs_submissions

ALTER TABLE public.aifs_submissions ADD COLUMN IF NOT EXISTS archived_at timestamptz;
ALTER TABLE public.aifs_submissions ADD COLUMN IF NOT EXISTS archive_note text;

-- Index for filtering by archived status
CREATE INDEX IF NOT EXISTS aifs_submissions_archived_at_idx ON public.aifs_submissions(archived_at) WHERE archived_at IS NOT NULL;
