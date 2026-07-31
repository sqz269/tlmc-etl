-- Applies generate_track_map.py output. Run from the directory holding the
-- CSV: psql "$CONN" -f apply_track_map.sql
--
-- The track_map table itself is backend-owned (EF migration AddTrackMap);
-- this script only loads it. Wipe-and-reload like similar_track: coordinates
-- and cluster labels from different layout runs are meaningless side by side,
-- so partial loads are never allowed.
--
-- year, work_id and circle_id are denormalized here at load time (release
-- date through disc, the first original work the track arranges, and the
-- release's primary circle) so the serving endpoint is a single-table scan.
-- Tracks without playable media are skipped: every point on the map must
-- produce sound when clicked.

BEGIN;

CREATE TEMP TABLE tmp_track_map (
    track_id uuid,
    x        real,
    y        real,
    cluster  smallint
) ON COMMIT DROP;

\copy tmp_track_map FROM 'track_map.csv' WITH CSV

TRUNCATE track_map;

INSERT INTO track_map (track_id, x, y, cluster, year, work_id, circle_id)
SELECT m.track_id,
       m.x,
       m.y,
       m.cluster,
       extract(year FROM r.release_date)::smallint,
       ow.original_work_id,
       pc.circle_id
FROM tmp_track_map m
JOIN track t ON t.id = m.track_id
JOIN disc d ON d.id = t.disc_id
JOIN release r ON r.id = d.release_id
LEFT JOIN LATERAL (
    SELECT os.original_work_id
    FROM track_original_song tos
    JOIN original_song os ON os.id = tos.original_song_id
    WHERE tos.track_id = m.track_id
    ORDER BY os.original_work_id
    LIMIT 1
) ow ON true
LEFT JOIN LATERAL (
    SELECT rc.circle_id
    FROM release_circle rc
    WHERE rc.release_id = r.id
    ORDER BY rc.ordinal
    LIMIT 1
) pc ON true
WHERE cardinality(t.hls_bitrates) > 0 OR t.has_dash;

COMMIT;

ANALYZE track_map;
