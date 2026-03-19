-- Add columns to support YouTube video imports alongside blog articles
ALTER TABLE links ADD COLUMN IF NOT EXISTS content_type text NOT NULL DEFAULT 'article';
ALTER TABLE links ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE links ADD COLUMN IF NOT EXISTS transcript text;

COMMENT ON COLUMN links.content_type IS 'Content type: article, video';
COMMENT ON COLUMN links.description IS 'Video description or article excerpt';
COMMENT ON COLUMN links.transcript IS 'Video transcript (YouTube auto-captions)';
