-- Loads the curated cluster display names (cluster_display_names.csv — the
-- name_clusters_muq.py proposals after human review) into the backend-owned
-- track_map_cluster table. Run from the directory holding the CSV:
--   psql "$CONN" -f apply_cluster_names.sql
--
-- Names are only meaningful for the layout run they were listened against:
-- k-means labels are relabeled by size each generate_track_map.py run, so a
-- re-layout MUST be followed by re-naming (or by truncating this table until
-- names exist again). Wipe-and-reload, same discipline as track_map itself.

BEGIN;

CREATE TEMP TABLE tmp_cluster_names (
    cluster smallint,
    name    text
) ON COMMIT DROP;

\copy tmp_cluster_names FROM 'cluster_display_names.csv' WITH CSV

TRUNCATE track_map_cluster;

INSERT INTO track_map_cluster (cluster, name)
SELECT cluster, name FROM tmp_cluster_names;

COMMIT;
