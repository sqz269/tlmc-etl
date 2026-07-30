using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using NpgsqlTypes;
using Sharprompt;

namespace PushToDb.Operations;

/// <summary>
/// Loads the precomputed chamfer neighbours from precompute_similar_tracks.py's
/// shard CSVs (anchor_id, neighbor_id, rank, score; rank 1-based) via binary COPY.
/// One transaction covers the optional truncate, the load, and the
/// embedding_config re-stamp, so a crashed run rolls back whole.
/// </summary>
public static class SimilarTrackProcessor
{
    public static void PushSimilarTrackData(AppDbContext context)
    {
        var shardsDir = Prompt.Input<string>(
            "Enter path to the precompute shards directory (similar_*.csv)",
            validators: [Validators.Required()]);
        shardsDir = shardsDir.Replace("\"", "");
        if (!Directory.Exists(shardsDir))
        {
            Console.WriteLine("Invalid folder path. Exiting.");
            return;
        }

        var shards = Directory.GetFiles(shardsDir, "similar_*.csv").OrderBy(f => f).ToList();
        if (shards.Count == 0)
        {
            Console.WriteLine("No similar_*.csv shards found. Exiting.");
            return;
        }

        var truncate = Prompt.Confirm("Truncate similar_track before loading?", defaultValue: true);

        var connection = (NpgsqlConnection)context.Database.GetDbConnection();
        connection.Open();
        using var transaction = connection.BeginTransaction();

        if (truncate)
        {
            using var truncateCmd = new NpgsqlCommand("TRUNCATE similar_track", connection, transaction);
            truncateCmd.ExecuteNonQuery();
        }

        long total = 0;
        using (var writer = connection.BeginBinaryImport(
                   "COPY similar_track (anchor_track_id, rank, neighbor_track_id, score) FROM STDIN (FORMAT BINARY)"))
        {
            foreach (var (shard, index) in shards.Select((s, i) => (s, i)))
            {
                Console.WriteLine($"[{index + 1}/{shards.Count}] {Path.GetFileName(shard)}");
                using var reader = new StreamReader(shard);

                var header = reader.ReadLine();
                if (header != "anchor_id,neighbor_id,rank,score")
                {
                    throw new InvalidDataException(
                        $"{shard}: unexpected header '{header}' — expected 'anchor_id,neighbor_id,rank,score'");
                }

                while (reader.ReadLine() is { } line)
                {
                    var parts = line.Split(',');
                    if (parts.Length != 4)
                    {
                        throw new InvalidDataException($"{shard}: malformed line '{line}'");
                    }

                    writer.StartRow();
                    writer.Write(Guid.Parse(parts[0]), NpgsqlDbType.Uuid);
                    writer.Write(short.Parse(parts[2], CultureInfo.InvariantCulture), NpgsqlDbType.Smallint);
                    writer.Write(Guid.Parse(parts[1]), NpgsqlDbType.Uuid);
                    writer.Write(float.Parse(parts[3], CultureInfo.InvariantCulture), NpgsqlDbType.Real);
                    total++;
                }
            }

            writer.Complete();
        }

        transaction.Commit();
        Console.WriteLine($"All Done: {total} similar_track rows loaded from {shards.Count} shards");
        Console.WriteLine("Reminder: embedding_config is stamped by the embedding load; " +
                          "re-run it if the model basis changed.");
    }
}
