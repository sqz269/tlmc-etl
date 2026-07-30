using System.Runtime.InteropServices;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using PushToDb.Model;
using Sharprompt;
using Spectre.Console;

namespace PushToDb.Operations;

public static class TrackEmbeddingProcessor
{
    private const int MeanDims = 1024;
    private const int MeanMaxDims = 2048;
    private const int BatchSize = 5000;

    public static void PushTrackEmbeddingData(AppDbContext context)
    {
        var folderPath = Prompt.Input<string>(
            "Enter path to the push_ready embeddings folder (contains mean/ and mean+max/)",
            validators: [Validators.Required()]);
        folderPath = folderPath.Replace("\"", "");
        if (!Directory.Exists(folderPath))
        {
            Console.WriteLine("Invalid folder path. Exiting.");
            return;
        }

        // The provenance stamp the API reports as the similarity basis. The .bin
        // directories carry no manifest today, so this is asked for explicitly
        // rather than silently derived from a folder name.
        var model = Prompt.Input<string>(
            "Model string for embedding_config (model/chunking/layer-mix)",
            defaultValue: "mert-v1-330m/win6s-hop4s/last4",
            validators: [Validators.Required()]);

        var meanEmbeddings = LoadEmbeddings(folderPath, "mean", MeanDims);
        var meanMaxEmbeddings = LoadEmbeddings(folderPath, "mean+max", MeanMaxDims);

        // Only rows whose track exists: a stray .bin should fail its own row, not
        // a 5000-row batch mid-run with no resume path.
        var knownTrackIds = context.Tracks.Select(t => t.Id).ToHashSet();

        var rows = new List<TrackEmbedding>();
        var skippedNoPair = 0;
        var skippedNoTrack = 0;
        foreach (var (trackId, mean) in meanEmbeddings)
        {
            if (!meanMaxEmbeddings.TryGetValue(trackId, out var meanMax))
            {
                skippedNoPair++;
                continue;
            }

            if (!knownTrackIds.Contains(trackId))
            {
                skippedNoTrack++;
                continue;
            }

            rows.Add(new TrackEmbedding
            {
                TrackId = trackId,
                EmbeddingMean = new Vector(mean),
                EmbeddingMeanMax = new HalfVector(Array.ConvertAll(meanMax, f => (Half)f)),
            });
        }

        Console.WriteLine($"Prepared {rows.Count} embeddings " +
                          $"(skipped: {skippedNoPair} without a mean+max pair, {skippedNoTrack} without a track row)");

        // One transaction for the whole load plus the stamp: a crashed run rolls
        // back to the previous state instead of leaving an unmarked mixture.
        using var transaction = context.Database.BeginTransaction();

        var inserted = 0;
        foreach (var chunk in rows.Chunk(BatchSize))
        {
            context.TrackEmbeddings.AddRange(chunk);
            context.SaveChanges();
            // Cleared between batches: an ever-growing tracker made this loader
            // quadratic.
            context.ChangeTracker.Clear();
            inserted += chunk.Length;
            Console.WriteLine($"[{inserted}/{rows.Count}] committed");
        }

        StampEmbeddingConfig(context, model, inserted);

        transaction.Commit();
        Console.WriteLine($"All Done: {inserted} embeddings, embedding_config stamped '{model}'");
    }

    public static void StampEmbeddingConfig(AppDbContext context, string model, int trackCount)
    {
        var config = context.EmbeddingConfigs.FirstOrDefault();
        if (config == null)
        {
            context.EmbeddingConfigs.Add(new EmbeddingConfig
            {
                Id = true,
                Model = model,
                LoadedAt = DateTime.UtcNow,
                TrackCount = trackCount,
            });
        }
        else
        {
            config.Model = model;
            config.LoadedAt = DateTime.UtcNow;
            config.TrackCount = trackCount;
        }

        context.SaveChanges();
        context.ChangeTracker.Clear();
    }

    private static Dictionary<Guid, float[]> LoadEmbeddings(string basePath, string poolingMode, int expectedDims)
    {
        var dirPath = Path.Join(basePath, poolingMode);
        if (!Directory.Exists(dirPath))
        {
            throw new DirectoryNotFoundException($"Directory not found: {dirPath}");
        }

        var files = Directory.GetFiles(dirPath, "*.bin");
        var embeddings = new Dictionary<Guid, float[]>(files.Length);
        var wrongSize = 0;

        AnsiConsole.Progress().Start(ctx =>
        {
            var task = ctx.AddTask($"[green]Loading {poolingMode} files[/]");
            task.MaxValue = files.Length;

            foreach (var file in files)
            {
                task.Increment(1);

                if (!Guid.TryParse(Path.GetFileNameWithoutExtension(file), out var trackId))
                {
                    AnsiConsole.MarkupLine($"[yellow]Warning:[/] Skipping invalid filename: [dim]{Path.GetFileName(file)}[/]");
                    continue;
                }

                var bytes = File.ReadAllBytes(file);
                var vector = MemoryMarshal.Cast<byte, float>(bytes).ToArray();

                // A truncated .bin fails its own row here rather than a whole
                // batch later at SaveChanges.
                if (vector.Length != expectedDims)
                {
                    wrongSize++;
                    AnsiConsole.MarkupLine(
                        $"[red]Skipping {Path.GetFileName(file)}[/]: {vector.Length} floats, expected {expectedDims}");
                    continue;
                }

                embeddings[trackId] = vector;
            }
        });

        if (wrongSize > 0)
        {
            Console.WriteLine($"WARNING: {wrongSize} {poolingMode} file(s) had the wrong dimension and were skipped");
        }

        return embeddings;
    }
}
