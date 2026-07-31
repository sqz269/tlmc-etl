-- Exports the tracks name_clusters_muq.py listens to: per map cluster, the 10
-- medoids (closest to the pgvector centroid of the cluster's pooled MERT
-- embeddings) plus 6 uniform-random members as a spread check.
--
--   psql "$CONN" -f sample_cluster_tracks.sql > cluster_sample.csv   -- or COPY
--
-- Columns: cluster, track_id, role, title, media_key

COPY (
WITH cm AS (
  SELECT m.cluster, avg(e.embedding_mean) AS centroid
  FROM track_map m JOIN track_embedding e ON e.track_id = m.track_id
  GROUP BY m.cluster
),
medoids AS (
  SELECT m.cluster, m.track_id, t.media_key, t.name->>'default' AS title,
         row_number() OVER (PARTITION BY m.cluster ORDER BY e.embedding_mean <=> cm.centroid) AS rn
  FROM track_map m
  JOIN track_embedding e ON e.track_id = m.track_id
  JOIN cm ON cm.cluster = m.cluster
  JOIN track t ON t.id = m.track_id
  WHERE t.media_key IS NOT NULL
),
randoms AS (
  SELECT m.cluster, m.track_id, t.media_key, t.name->>'default' AS title,
         row_number() OVER (PARTITION BY m.cluster ORDER BY random()) AS rn
  FROM track_map m
  JOIN track t ON t.id = m.track_id
  WHERE t.media_key IS NOT NULL
)
SELECT cluster, track_id, 'medoid', title, media_key FROM medoids WHERE rn <= 10
UNION ALL
SELECT cluster, track_id, 'random', title, media_key FROM randoms WHERE rn <= 6
) TO STDOUT WITH CSV
