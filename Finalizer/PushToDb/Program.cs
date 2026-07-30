using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Npgsql;
using Pgvector.EntityFrameworkCore;
using PushToDb;
using PushToDb.Model;
using PushToDb.Operations;
using PushToDb.UserOptions;
using Sharprompt;

// Connection string comes from the environment; the previous build hardcoded a
// password into source.
var connectionString = Environment.GetEnvironmentVariable("TLMC_DB_CONNECTION")
    ?? Prompt.Input<string>("Enter the Postgres connection string (or set TLMC_DB_CONNECTION)");

Console.WriteLine("Initializing DB Connection");

AppDbContext appDbContext;
try
{
    var dataSourceBuilder = new NpgsqlDataSourceBuilder(connectionString);

    // jsonb keys are part of the schema (name->>'default' feeds the generated
    // sort columns), so the serializer options here must match the backend's.
    dataSourceBuilder.EnableDynamicJson();
    dataSourceBuilder.ConfigureJsonOptions(new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    });
    dataSourceBuilder.UseVector();
    dataSourceBuilder.MapEnum<StorageRoot>("storage_root");
    dataSourceBuilder.MapEnum<CreditRole>("credit_role");
    var dataSource = dataSourceBuilder.Build();

    var dbContextOptions = new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(dataSource, o =>
        {
            o.UseVector();
            o.MapEnum<StorageRoot>("storage_root");
            o.MapEnum<CreditRole>("credit_role");
            o.CommandTimeout(600);
        })
        .UseSnakeCaseNamingConvention()
        .LogTo(Console.WriteLine, LogLevel.Warning)
        .Options;
    appDbContext = new AppDbContext(dbContextOptions);
}
catch (Exception e)
{
    Console.WriteLine("Fatal: Error initializing DB Connection");
    Console.WriteLine(e);

    Console.WriteLine("Press any key to exit");
    Console.ReadKey();
    return;
}

// Non-interactive mode for unattended runs; no args falls through to the menu.
if (args.Length > 0)
{
    switch (args[0])
    {
        case "circles" when args.Length == 2:
            CircleMetadataProcessor.PushBasicCircleData(appDbContext, args[1]);
            return;
        case "catalog" when args.Length == 4:
            AlbumTrackMetadataProcessor.PushBasicAlbumAndTrackData(appDbContext, args[1], args[2], args[3]);
            return;
        case "embeddings" when args.Length is 2 or 3:
            TrackEmbeddingProcessor.PushTrackEmbeddingData(
                appDbContext, args[1], args.Length == 3 ? args[2] : "mert-v1-330m/win6s-hop4s/last4");
            return;
        case "similar" when args.Length >= 2:
            SimilarTrackProcessor.PushSimilarTrackData(
                appDbContext, args[1], truncateFirst: !args.Contains("--no-truncate"));
            return;
        default:
            Console.WriteLine("Usage:");
            Console.WriteLine("  PushToDb circles <merged_artists.json>");
            Console.WriteLine("  PushToDb catalog <assigned_megered.json> <hls.finalized.output.json> <library-root-prefix>");
            Console.WriteLine("  PushToDb embeddings <push_ready-folder> [model-string]");
            Console.WriteLine("  PushToDb similar <shards-dir> [--no-truncate]");
            Environment.Exit(1);
            return;
    }
}

var opt = Prompt.Select<UserOptionDataOptions>("Select the data you want to push to the database (Use Arrow keys to select)", pageSize: 6);

switch (opt)
{
    case UserOptionDataOptions.AlbumTrackBasicMetadata:
        AlbumTrackMetadataProcessor.PushBasicAlbumAndTrackData(appDbContext);
        break;
    case UserOptionDataOptions.CircleBasicMetadata:
        CircleMetadataProcessor.PushBasicCircleData(appDbContext);
        break;
    case UserOptionDataOptions.TrackEmbeddingData:
        TrackEmbeddingProcessor.PushTrackEmbeddingData(appDbContext);
        break;
    case UserOptionDataOptions.SimilarTrackData:
        SimilarTrackProcessor.PushSimilarTrackData(appDbContext);
        break;
    default:
        throw new ArgumentOutOfRangeException();
}
