-- Applies generate_artwork_variants.py output. Run from the directory holding
-- the CSVs: psql "$CONN" -f apply_artwork_variants.sql
--
-- Conflict-safe for reruns: asset rows dedupe on (root, storage_key), and the
-- ladder insert resolves asset ids through storage_key so a rerun with freshly
-- minted uuids still attaches to the assets that already won.

BEGIN;

CREATE TEMP TABLE tmp_variant_file (
    asset_id    uuid,
    storage_key text,
    name        text,
    mime        text,
    byte_size   bigint
) ON COMMIT DROP;

CREATE TEMP TABLE tmp_variant (
    artwork_id uuid,
    size_px    smallint,
    asset_id   uuid
) ON COMMIT DROP;

CREATE TEMP TABLE tmp_colors (
    artwork_id uuid,
    colors     text[]
) ON COMMIT DROP;

\copy tmp_variant_file FROM 'variant_files.csv' WITH CSV
\copy tmp_variant FROM 'variants.csv' WITH CSV
\copy tmp_colors FROM 'colors.csv' WITH CSV

INSERT INTO asset (id, root, storage_key, name, mime, byte_size)
SELECT asset_id, 'library'::storage_root, storage_key, name, mime, byte_size
FROM tmp_variant_file
ON CONFLICT (root, storage_key) DO NOTHING;

-- Resized rungs: resolve through storage_key (see header). Size-0 rows point
-- at the already-existing source asset and insert directly.
INSERT INTO artwork_variant (artwork_id, size_px, asset_id)
SELECT v.artwork_id, v.size_px, a.id
FROM tmp_variant v
JOIN tmp_variant_file f ON f.asset_id = v.asset_id
JOIN asset a ON a.root = 'library'::storage_root AND a.storage_key = f.storage_key
ON CONFLICT (artwork_id, size_px) DO NOTHING;

INSERT INTO artwork_variant (artwork_id, size_px, asset_id)
SELECT artwork_id, size_px, asset_id
FROM tmp_variant
WHERE size_px = 0
ON CONFLICT (artwork_id, size_px) DO NOTHING;

UPDATE artwork a
SET colors = c.colors
FROM tmp_colors c
WHERE a.id = c.artwork_id;

COMMIT;
