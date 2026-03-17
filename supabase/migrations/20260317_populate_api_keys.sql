-- Generate API keys for all existing people who don't have one yet
UPDATE public.people
SET api_key = 'als_' || encode(gen_random_bytes(24), 'hex')
WHERE api_key IS NULL;

-- Set a default for the api_key column so new people get keys automatically
ALTER TABLE public.people
  ALTER COLUMN api_key SET DEFAULT 'als_' || encode(gen_random_bytes(24), 'hex');
