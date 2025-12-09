using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Npgsql;
using PushToDb;
using PushToDb.Operations;
using PushToDb.UserOptions;
using Sharprompt;

// Vector support currently broken
// See: https://github.com/pgvector/pgvector-dotnet/issues/51
// Wait for 0.3.0 release


//NpgsqlConnection.GlobalTypeMapper.EnableDynamicJson();
NpgsqlConnection.GlobalTypeMapper.UseVector();

const string POSTGRES_CONNECTION_STRING = "Host=192.168.29.223;Port=30064;Username=postgres;Password=postgrespw;Database=postgres";

Console.WriteLine("Initializing DB Connection");

AppDbContext appDbContext;
try
{
    var dataSourceBuilder = new NpgsqlDataSourceBuilder(POSTGRES_CONNECTION_STRING);
    dataSourceBuilder.UseVector();
    var dataSource = dataSourceBuilder.Build();
    NpgsqlConnection.GlobalTypeMapper.UseVector();

    var dbContextOptions = new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(dataSource, o =>
        {
            o.UseVector();
        })
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

NpgsqlConnection.GlobalTypeMapper.UseVector();

var opt = Prompt.Select<UserOptionDataOptions>("Select the data you want to push to the database (Use Arrow keys to select)", pageSize: 5);

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
    default:
        throw new ArgumentOutOfRangeException();
}
