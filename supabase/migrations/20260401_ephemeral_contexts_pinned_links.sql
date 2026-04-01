-- Ephemeral link contexts and pinned links (ADR 004)

-- 1. Add is_pinned to links
ALTER TABLE links ADD COLUMN is_pinned boolean NOT NULL DEFAULT false;

-- 2. Create link_contexts table
CREATE TABLE link_contexts (
  id          text PRIMARY KEY DEFAULT generate_prefixed_id('ctx-'),
  label       text NOT NULL,
  slug        text UNIQUE NOT NULL,
  expires_at  timestamptz,
  archived_at timestamptz,
  created_at  timestamptz DEFAULT now()
);

-- Enable RLS on link_contexts (consistent with other tables)
ALTER TABLE link_contexts ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "service_role_all" ON link_contexts
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- 3. Add context_id to tracking_variants
ALTER TABLE tracking_variants ADD COLUMN context_id text REFERENCES link_contexts(id);

-- 4. Add note to tracking_variants
ALTER TABLE tracking_variants ADD COLUMN note text;

-- 5. Add expires_at to tracking_variants
ALTER TABLE tracking_variants ADD COLUMN expires_at timestamptz;
