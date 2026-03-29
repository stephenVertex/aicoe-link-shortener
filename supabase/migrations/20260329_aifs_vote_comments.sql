-- Allow comments on aifs submissions without re-voting
-- A person can vote once but comment as many times as they want

ALTER TABLE public.aifs_votes ADD COLUMN IF NOT EXISTS type text NOT NULL DEFAULT 'vote' CHECK (type IN ('vote', 'comment'));

-- Drop old unique constraint (one entry per person)
ALTER TABLE public.aifs_votes DROP CONSTRAINT IF EXISTS aifs_votes_submission_id_person_ref_key;

-- New partial unique index: one VOTE per person per submission, but unlimited comments
CREATE UNIQUE INDEX IF NOT EXISTS aifs_votes_one_vote_per_person ON public.aifs_votes(submission_id, person_ref) WHERE type = 'vote';
