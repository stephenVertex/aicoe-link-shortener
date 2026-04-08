CREATE OR REPLACE FUNCTION slice_srt_transcript(
  p_srt TEXT,
  p_start_sec FLOAT,
  p_end_sec FLOAT
) RETURNS TEXT AS $func$
DECLARE
  nl TEXT := chr(10);
  dnl TEXT := chr(10) || chr(10);
  srt_pattern TEXT;
  srt_check TEXT;
  v_result TEXT;
BEGIN
  srt_pattern := '^(\d+)' || nl || '(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})' || nl || '([\s\S]*)$';
  srt_check := '^\d+' || nl || '\d{2}:\d{2}:\d{2}';

  WITH blocks AS (
    SELECT trim(unnest(regexp_split_to_array(p_srt, dnl))) AS block
  ),
  parsed AS (
    SELECT 
      (regexp_match(block, srt_pattern)) AS m
    FROM blocks
    WHERE block ~ srt_check
  ),
  extracted AS (
    SELECT
      m[1]::int AS orig_idx,
      m[2] AS start_ts,
      m[3] AS end_ts,
      (substring(m[2], 1, 2)::int * 3600 + substring(m[2], 4, 2)::int * 60 + substring(m[2], 7, 2)::int + substring(m[2], 10, 3)::float / 1000) AS start_sec,
      (substring(m[3], 1, 2)::int * 3600 + substring(m[3], 4, 2)::int * 60 + substring(m[3], 7, 2)::int + substring(m[3], 10, 3)::float / 1000) AS end_sec,
      m[4] AS text
    FROM parsed
  ),
  in_range AS (
    SELECT start_ts, end_ts, text, orig_idx,
      ROW_NUMBER() OVER (ORDER BY orig_idx) AS new_idx
    FROM extracted
    WHERE end_sec > p_start_sec AND start_sec < p_end_sec
  )
  SELECT string_agg(
    new_idx::text || nl || start_ts || ' --> ' || end_ts || nl || text,
    dnl ORDER BY new_idx
  ) INTO v_result
  FROM in_range;
  
  RETURN v_result;
END;
$func$ LANGUAGE plpgsql STABLE;
