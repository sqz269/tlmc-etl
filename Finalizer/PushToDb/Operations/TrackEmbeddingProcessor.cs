using Pgvector;
using PushToDb.Model;
using Spectre.Console; // Added Namespace
using System.Runtime.InteropServices;

namespace PushToDb.Operations;

public class TrackEmbeddingProcessor
{
    // Helper to configure a consistent look for all progress bars
    private static ProgressColumn[] GetProgressColumns()
    {
        return new ProgressColumn[]
        {
            new TaskDescriptionColumn(),    // "Loading embeddings..."
            new ProgressBarColumn(),        // The visual [====] bar
            new PercentageColumn(),         // 50%
            new SpinnerColumn(),            // Moving spinner
            new RemainingTimeColumn(),      // "00:05 remaining"
        };
    }

    public static Dictionary<Guid, float[]> LoadEmbeddings(string basePath, string poolingMode)
    {
        var dirpath = Path.Join(basePath, poolingMode);
        if (!Directory.Exists(dirpath))
        {
            throw new DirectoryNotFoundException($"Directory not found: {dirpath}");
        }

        var files = Directory.GetFiles(dirpath, "*.bin");
        var embeddings = new Dictionary<Guid, float[]>();

        // Spectre.Console Progress Wrapper
        AnsiConsole.Progress()
            .Columns(GetProgressColumns())
            .Start(ctx =>
            {
                // Create the task
                var task = ctx.AddTask($"[green]Loading {poolingMode} files[/]");
                task.MaxValue = files.Length;

                foreach (var file in files)
                {
                    if (Guid.TryParse(Path.GetFileNameWithoutExtension(file), out Guid trackId))
                    {
                        byte[] bytes = File.ReadAllBytes(file);
                        var vectorData = MemoryMarshal.Cast<byte, float>(bytes).ToArray();
                        embeddings[trackId] = vectorData;
                    }
                    else
                    {
                        // Log warning above the bar without breaking UI
                        AnsiConsole.MarkupLine($"[yellow]Warning:[/] Skipping invalid filename: [dim]{Path.GetFileName(file)}[/]");
                    }

                    // Increment progress by 1
                    task.Increment(1);
                }
            });

        return embeddings;
    }

    public static List<TrackEmbedding> LoadFromPythonExport(string folderPath)
    {
        // 1. Load Mean (Will show its own progress bar)
        var meanEmbeddings = LoadEmbeddings(folderPath, "mean");

        // 2. Load Mean+Max (Will show its own progress bar)
        var meanMaxEmbeddings = LoadEmbeddings(folderPath, "mean+max");

        var trackEmbeddings = new List<TrackEmbedding>();

        // 3. Merge process (Will show a fast progress bar)
        AnsiConsole.Progress()
            .Columns(GetProgressColumns())
            .Start(ctx =>
            {
                var task = ctx.AddTask("[blue]Merging Vectors[/]");
                task.MaxValue = meanEmbeddings.Count;

                foreach (var kvp in meanEmbeddings)
                {
                    var trackId = kvp.Key;
                    var meanVector = kvp.Value;

                    if (meanMaxEmbeddings.TryGetValue(trackId, out var meanMaxVector))
                    {
                        var trackEmbedding = new TrackEmbedding
                        {
                            TrackId = trackId,
                            EmbeddingMean = new Vector(meanVector),
                            EmbeddingMeanMax = new Vector(meanMaxVector)
                        };
                        trackEmbeddings.Add(trackEmbedding);
                    }
                    else
                    {
                        AnsiConsole.MarkupLine($"[red]Error:[/] No mean+max embedding found for Track ID {trackId}");
                    }

                    task.Increment(1);
                }
            });

        return trackEmbeddings;
    }

    public static void PushTrackEmbeddingData(AppDbContext appDbContext)
    {
        // Use Spectre to ask for input nicely
        var folderPath = AnsiConsole.Ask<string>("Enter the [green]folder path[/] containing the .bin files:");

        // Clean up quotes if user copy-pasted a path with quotes
        folderPath = folderPath.Replace("\"", "");

        if (!Directory.Exists(folderPath))
        {
            AnsiConsole.MarkupLine("[red]Invalid folder path. Exiting.[/]");
            return;
        }

        AnsiConsole.MarkupLine("[bold]Step 1: Loading Data[/]");
        var trackEmbeddings = LoadFromPythonExport(folderPath);

        AnsiConsole.WriteLine(); // Spacer
        AnsiConsole.MarkupLine($"[bold]Step 2: Pushing {trackEmbeddings.Count} records to Database[/]");

        const int batchSize = 5000;

        // DB Insert Progress
        AnsiConsole.Progress()
            .Columns(GetProgressColumns())
            .Start(ctx =>
            {
                var task = ctx.AddTask("[purple]Bulk Inserting...[/]");
                task.MaxValue = trackEmbeddings.Count;

                for (int i = 0; i < trackEmbeddings.Count; i += batchSize)
                {
                    var batch = trackEmbeddings.Skip(i).Take(batchSize).ToList();

                    appDbContext.TrackEmbeddings.AddRange(batch);
                    appDbContext.SaveChanges();

                    // Increment by the actual batch size
                    task.Increment(batch.Count);
                }
            });

        AnsiConsole.MarkupLine("[bold green]Success![/] All track embeddings pushed to the database.");
    }
}