using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using NpgsqlTypes;
using Sharprompt;

namespace PushToDb.Operations;

/// <summary>
/// Loads release and circle level similarity from precompute_similar_groups.py's
/// ranked CSVs (one file per flavor, identical columns; anchors are entity uuids
/// from the --track-release-csv / --release-circle-csv exports). The three top
/// lists are merged into one row per (anchor, neighbor) with a nullable rank per
/// flavor — the backend's similar_release / similar_circle union shape. One
/// transaction covers the optional truncates and both tables, so a crashed run
/// rolls back whole.
/// </summary>
public static class SimilarGroupProcessor
{
    private const string ExpectedHeader =
        "anchor_id,neighbor_id,rank,score_style,score_raw,score_kde";

    private static readonly (string Stem, string Table, string Columns)[] Levels =
    [
        ("similar_albums", "similar_release",
            "anchor_release_id, neighbor_release_id, rank_style, rank_raw, rank_kde, "
            + "score_style, score_raw, score_kde"),
        ("similar_circles", "similar_circle",
            "anchor_circle_id, neighbor_circle_id, rank_style, rank_raw, rank_kde, "
            + "score_style, score_raw, score_kde"),
    ];

    private sealed class GroupRow
    {
        public short? RankStyle;
        public short? RankRaw;
        public short? RankKde;
        public float ScoreStyle;
        public float ScoreRaw;
        public float ScoreKde;
    }

    public static void PushSimilarGroupData(
        AppDbContext context, string? groupsDirectory = null, bool? truncateFirst = null)
    {
        var dir = groupsDirectory ?? Prompt.Input<string>(
            "Enter path to the group precompute output (similar_albums*.csv, similar_circles*.csv)",
            validators: [Validators.Required()]);
        dir = dir.Replace("\"", "");
        if (!Directory.Exists(dir))
        {
            Console.WriteLine("Invalid folder path. Exiting.");
            return;
        }

        var truncate = truncateFirst
            ?? Prompt.Confirm("Truncate similar_release and similar_circle before loading?",
                defaultValue: true);

        var connection = (NpgsqlConnection)context.Database.GetDbConnection();
        connection.Open();
        using var transaction = connection.BeginTransaction();

        foreach (var (stem, table, columns) in Levels)
        {
            var merged = MergeFlavors(dir, stem);

            if (truncate)
            {
                using var truncateCmd = new NpgsqlCommand(
                    $"TRUNCATE {table}", connection, transaction);
                truncateCmd.ExecuteNonQuery();
            }

            using var writer = connection.BeginBinaryImport(
                $"COPY {table} ({columns}) FROM STDIN (FORMAT BINARY)");
            writer.Timeout = TimeSpan.FromHours(1);
            foreach (var ((anchor, neighbor), row) in merged)
            {
                writer.StartRow();
                writer.Write(anchor, NpgsqlDbType.Uuid);
                writer.Write(neighbor, NpgsqlDbType.Uuid);
                WriteNullableRank(writer, row.RankStyle);
                WriteNullableRank(writer, row.RankRaw);
                WriteNullableRank(writer, row.RankKde);
                writer.Write(row.ScoreStyle, NpgsqlDbType.Real);
                writer.Write(row.ScoreRaw, NpgsqlDbType.Real);
                writer.Write(row.ScoreKde, NpgsqlDbType.Real);
            }

            writer.Complete();
            Console.WriteLine($"{table}: {merged.Count} union rows loaded");
        }

        transaction.Commit();
        Console.WriteLine("All Done. Reminder: embedding_config is stamped by the "
                          + "embedding load; re-run it if the model basis changed.");
    }

    private static void WriteNullableRank(NpgsqlBinaryImporter writer, short? rank)
    {
        if (rank == null)
        {
            writer.WriteNull();
        }
        else
        {
            writer.Write(rank.Value, NpgsqlDbType.Smallint);
        }
    }

    private static Dictionary<(Guid, Guid), GroupRow> MergeFlavors(string dir, string stem)
    {
        var merged = new Dictionary<(Guid, Guid), GroupRow>();
        foreach (var (flavor, fileName) in new[]
                 {
                     ("style", $"{stem}.csv"),
                     ("raw", $"{stem}_raw.csv"),
                     ("kde", $"{stem}_kde.csv"),
                 })
        {
            var path = Path.Combine(dir, fileName);
            if (!File.Exists(path))
            {
                throw new FileNotFoundException(
                    $"{fileName} missing — the precompute writes all three flavor files", path);
            }

            using var reader = new StreamReader(path);
            var header = reader.ReadLine();
            if (header != ExpectedHeader)
            {
                throw new InvalidDataException(
                    $"{fileName}: unexpected header '{header}' — expected '{ExpectedHeader}'");
            }

            while (reader.ReadLine() is { } line)
            {
                var parts = line.Split(',');
                if (parts.Length != 6)
                {
                    throw new InvalidDataException($"{fileName}: malformed line '{line}'");
                }

                var key = (Guid.Parse(parts[0]), Guid.Parse(parts[1]));
                var rank = short.Parse(parts[2], CultureInfo.InvariantCulture);
                if (!merged.TryGetValue(key, out var row))
                {
                    row = merged[key] = new GroupRow
                    {
                        ScoreStyle = float.Parse(parts[3], CultureInfo.InvariantCulture),
                        ScoreRaw = float.Parse(parts[4], CultureInfo.InvariantCulture),
                        ScoreKde = float.Parse(parts[5], CultureInfo.InvariantCulture),
                    };
                }

                switch (flavor)
                {
                    case "style": row.RankStyle = rank; break;
                    case "raw": row.RankRaw = rank; break;
                    default: row.RankKde = rank; break;
                }
            }
        }

        return merged;
    }
}
