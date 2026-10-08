-- Marks a fact_observation row as excluded from version/restatement comparison. The row itself is
-- never deleted or mutated: this only controls whether version_resolver groups it with other facts
-- when looking for restatements/revisions. Used when the normalizer detects an intra-filing
-- duplicate-value anomaly (the same concept+dimensions+value tagged with two different periods
-- inside one filing, where one period does not match that filing's own reporting period -- a
-- filer-side XBRL context error, not a genuine historical value).
ALTER TABLE fact_observation ADD COLUMN IF NOT EXISTS excluded_from_versioning BOOLEAN DEFAULT FALSE;
ALTER TABLE fact_observation ADD COLUMN IF NOT EXISTS exclusion_reason VARCHAR(64);
