using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Npgsql;
using PushToDb;
using PushToDb.Operations;
using PushToDb.UserOptions;
using Sharprompt;

NpgsqlConnection.GlobalTypeMapper.EnableDynamicJson();

const string POSTGRES_CONNECTION_STRING = "Host=192.168.29.223;Port=30064;Username=postgres;Password=postgrespw;Database=postgres";

Console.WriteLine("Initializing DB Connection");

AppDbContext appDbContext;
try
{
    // Initialize AppDbContext
    var dbContext = new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(POSTGRES_CONNECTION_STRING)
        .LogTo(Console.WriteLine, LogLevel.Warning);

    appDbContext = new AppDbContext(dbContext.Options);

    Console.WriteLine("DB Connection Initialized");
}
catch (Exception e)
{
    Console.WriteLine("Fatal: Error initializing DB Connection");
    Console.WriteLine(e);

    Console.WriteLine("Press any key to exit");
    Console.ReadKey();
    return;
}


var opt = Prompt.Select<UserOptionDataOptions>("Select the data you want to push to the database (Use Arrow keys to select)", pageSize: 5);

switch (opt)
{
    case UserOptionDataOptions.AlbumTrackBasicMetadata:
        AlbumTrackMetadataProcessor.PushBasicAlbumAndTrackData(appDbContext);
        break;
    case UserOptionDataOptions.CircleBasicMetadata:
        CircleMetadataProcessor.PushBasicCircleData(appDbContext);
        break;
    case UserOptionDataOptions.MpegDashPlaylists:
        MpegDashPlaylistProcessor.PushMpegDashPlaylists(appDbContext);
        break;
    // case UserOptionDataOptions.ThwikiExtendedArtistCircleMetadata:
    //     UserThwikiExtendedArtistCircleMetadataOption.GetAndInvokeThwikiExtendedArtistCircleMetadataOption();
    //     break;
    // case UserOptionDataOptions.ThwikiExtendedAlbumTrackMetadata:
    //     UserThwikiExtendedAlbumTrackMetadataOption.GetAndInvokeThwikiExtendedAlbumTrackMetadataOption();
    //     break;
    // case UserOptionDataOptions.ThwikiLyricsData:
    //     UserThwikiLyricsDataOption.GetAndInvokeThwikiLyricsDataOption();
    //     break;
    default:
        throw new ArgumentOutOfRangeException();
}
