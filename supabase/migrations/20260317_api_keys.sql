-- Add API key column to people table for user CLI authentication
ALTER TABLE people ADD COLUMN api_key text UNIQUE;

-- Index for fast lookups by api_key
CREATE INDEX idx_people_api_key ON people (api_key) WHERE api_key IS NOT NULL;
