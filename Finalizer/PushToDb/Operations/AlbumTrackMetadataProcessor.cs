using System.ComponentModel.DataAnnotations;
using EFCore.BulkExtensions;
using Newtonsoft.Json;
using PushToDb.ExternalModel;
using PushToDb.Model;
using PushToDb.Utils;
using Sharprompt;

namespace PushToDb.Operations;

public record ObjectsToInsert(
    List<Album> Albums,
    List<Track> Tracks,
    List<HlsPlaylist> HlsPlaylists,
    List<HlsSegment> HlsSegments,
    List<Asset> Assets
)
{
    public Album GetMasterAlbum()
    {
        if (Albums.Count == 1)
        {
            return Albums.First();
        }

        return Albums.FirstOrDefault(a => a.DiscNumber == 0);
    }
};


public static class AlbumTrackMetadataProcessor
{
    public static List<Circle> GetCirclesByIds(AppDbContext context, List<Guid> id)
    {
        return context.Circles.Where(c => id.Contains(c.Id)).ToList();
    }


    public static List<HlsPlaylist> InstantiateHlsPlaylists(ObjectsToInsert insertTracker, Dictionary<string, HlsTrack> hlsData, string trackOriginalPath, Track track)
    {
        var hlsPlaylists = new List<HlsPlaylist>();
        // Get the HLS data for the track
        var hlsInfo = hlsData[trackOriginalPath];

        // Add master playlist
        var masterPlaylist = new HlsPlaylist
        {
            Id = Guid.NewGuid(),
            Type = HlsPlaylistType.Master,
            Bitrate = null,
            HlsPlaylistPath = hlsInfo.MasterPlaylist,
            Segments = [],
            Track = track,
            TrackId = track.Id
        };
        insertTracker.HlsPlaylists.Add(masterPlaylist);

        foreach (var (quality, mediaPlaylistInfo) in hlsInfo.MediaPlaylist)
        {
            var playlist = new HlsPlaylist
            {
                Id = Guid.NewGuid(),
                Type = HlsPlaylistType.Media,
                Bitrate = int.Parse(quality.Replace("k", "")),
                HlsPlaylistPath = mediaPlaylistInfo.Playlist,
                Segments = [],
                Track = track,
                TrackId = track.Id
            };

            foreach (var (segmentPath, segmentIndex) in mediaPlaylistInfo.Segments)
            {
                // Get filename from path
                var segmentName = Path.GetFileName(segmentPath);
                playlist.Segments.Add(new HlsSegment
                {
                    Id = Guid.NewGuid(),
                    Path = segmentPath,
                    Name = segmentName,
                    Index = segmentIndex,
                    HlsPlaylist = playlist,
                    HlsPlaylistId = playlist.Id
                });

                insertTracker.HlsSegments.Add(playlist.Segments.Last());
            }

            insertTracker.HlsPlaylists.Add(playlist);
            hlsPlaylists.Add(playlist);
        }

        return hlsPlaylists;
    }

    public static List<Track> InstantiateTracks(ObjectsToInsert insertTracker, Dictionary<string, HlsTrack> hlsData, List<JTrack> tracks)
    {
        // Each track has a list of HLS playlists (A track can have multiple qualities)
        var instantiated = new List<Track>();

        foreach (var jTrack in tracks)
        {
            var trackMetadata = jTrack.TrackMetadata;
            var track = new Track
            {
                Id = Guid.Parse(jTrack.TrackMetadata.TrackId),
                Name = trackMetadata.Title.AsLocalizedField(),
                Index = trackMetadata.Track,
                Staff = trackMetadata.Artist.Split(", ").ToList(),
            };

            var hlsPlaylists = InstantiateHlsPlaylists(insertTracker, hlsData, jTrack.TrackPath, track);

            insertTracker.Tracks.Add(track);
            instantiated.Add(track);
        }

        return instantiated;
    }

    public static List<Album> InstantiateDiscs(ObjectsToInsert insertTracker, JAlbum album, List<Circle> circles, Dictionary<string, HlsTrack> hlsData)
    {
        var albumMetadata = album.AlbumMetadata;

        var discs = album.Discs;

        var instantiated = new List<Album>();

        var numberOfDiscs = discs.Count;
        foreach (var jDisc in discs.Values)
        {
            // If there is only one disc, use the album id, 
            string id = numberOfDiscs == 1 ? album.AlbumMetadata.AlbumId : jDisc.DiscId;

            instantiated.Add(new Album
            {
                Id = Guid.Parse(id),
                Name = albumMetadata.AlbumName.AsLocalizedField(),
                ReleaseDate = albumMetadata.ReleaseDate.TryGetDateTime(),
                ReleaseConvention = albumMetadata.ReleaseConvention.GetNonEmptyStringOrNull(),
                CatalogNumber = albumMetadata.CatalogNumber.GetNonEmptyStringOrNull(),
                NumberOfDiscs = numberOfDiscs,
                DiscNumber = jDisc.DiscNumber,
                DiscName = jDisc.DiscName.GetNonEmptyStringOrNull(),

                AlbumArtist = circles,

                Tracks = InstantiateTracks(insertTracker, hlsData, jDisc.Tracks)
            });

            insertTracker.Albums.Add(instantiated.Last());
        }

        // Instantiate the master album if there are multiple discs
        if (numberOfDiscs > 1)
        {
            var masterAlbum = new Album
            {
                Id = Guid.Parse(albumMetadata.AlbumId),
                Name = albumMetadata.AlbumName.AsLocalizedField(),
                ReleaseDate = albumMetadata.ReleaseDate.TryGetDateTime(),
                ReleaseConvention = albumMetadata.ReleaseConvention.GetNonEmptyStringOrNull(),
                CatalogNumber = albumMetadata.CatalogNumber.GetNonEmptyStringOrNull(),
                NumberOfDiscs = numberOfDiscs,
                DiscNumber = 0,
                DiscName = null,

                AlbumArtist = circles
            };

            // Need to assign all discs as the child of the master album
            foreach (var disc in instantiated)
            {
                disc.ParentAlbum = masterAlbum;
            }

            insertTracker.Albums.Add(masterAlbum);
            instantiated.Add(masterAlbum);
        }

        return instantiated;
    }

    public static List<Asset> InstantiateAssets(ObjectsToInsert insertTracker, List<JAsset> assets)
    {
        var instantiated = new List<Asset>();

        foreach (var jAsset in assets)
        {
            instantiated.Add(new Asset
            {
                Id = Guid.Parse(jAsset.AssetId),
                Name = jAsset.AssetName,
                Path = jAsset.AssetPath
            });

            insertTracker.Assets.Add(instantiated.Last());
        }

        return instantiated;
    }

    public static void PushBasicAlbumAndTrackData(AppDbContext context)
    {
        var aggregatedFp = Prompt.Input<string>(
            "Enter path to assigned_megered.json",
            defaultValue: @"D:\PROG\TlmcTagger\TlmcInfoProviderV2\Processor\InfoCollector\Aggregator\output\assigned_megered.json",
            validators: [Validators.Required(), PathValidator.ValidateFilePath()]
        );
        var hlsFinalizedFp = Prompt.Input<string>(
            "Enter path to hls.finalized.output.json",
            defaultValue: @"D:\PROG\TlmcTagger\TlmcInfoProviderV2\Postprocessor\HlsTranscode\output\hls.finalized.output.json",
            validators: [Validators.Required(), PathValidator.ValidateFilePath()]);

        // Load both file to json
        Console.WriteLine("Loading Assignment Merged Data");
        var aggregated = JsonConvert.DeserializeObject<Dictionary<string, JAlbum>>(File.ReadAllText(aggregatedFp));
        Console.WriteLine("Assignment Merged Data Loaded");

        Console.WriteLine("Loading Hls Finalized Data");

        // open file stream, cuz the json is too big
        using var hlsFinalizedStream = new FileStream(hlsFinalizedFp, FileMode.Open, FileAccess.Read);
        using var hlsFinalizedReader = new StreamReader(hlsFinalizedStream);
        using var hlsFinalizedJsonReader = new JsonTextReader(hlsFinalizedReader);

        var hlsFinalized = new JsonSerializer().Deserialize<Dictionary<string, HlsTrack>>(hlsFinalizedJsonReader);

        Console.WriteLine("Hls Finalized Data Loaded");

        var queueObjects = new List<ObjectsToInsert>();

        var index = 0;
        var failed = 0;
        // Enumerate through the aggregated data
        foreach (var (albumId, albumData) in aggregated)
        {
            // Keep track of list of objects we actually need to insert
            var objectsToInsert = new ObjectsToInsert([], [], [], [], []);
            var albumArtists = GetCirclesByIds(context, albumData.AlbumMetadata.AlbumArtistIds.Select(Guid.Parse).ToList());

            try
            {
                var discsInstantiated = InstantiateDiscs(objectsToInsert, albumData, albumArtists, hlsFinalized);
            }
            // 
            catch (KeyNotFoundException e)
            {
                // if there is tracks that are not in hls.finalized.output.json, skip the album
                // Usually an indicator that the hls transcoding failed either due to corrupted files or other reasons
                Console.WriteLine(e);
                failed++;
                continue;
            }
            var assets = InstantiateAssets(objectsToInsert, albumData.Assets);

            // Find thumbnail from assets
            var thumbnail = assets.FirstOrDefault(a => a.Path == albumData.Thumbnail);
            if (thumbnail is not null)
            {
                objectsToInsert.Albums.ForEach(a => a.Image = thumbnail);
            }

            // Attach assets to albums, note that we only attach assets to master album if there are multiple discs
            var masterAlbum = objectsToInsert.GetMasterAlbum();
            if (masterAlbum is not null)
            {
                masterAlbum.OtherFiles = assets;
            }

            queueObjects.Add(objectsToInsert);

            index++;
            Console.WriteLine($"[{index} / {aggregated.Count} | {failed} ] {albumId}");
        }

        Console.WriteLine("Objects Instantiated. Starting DB Commit");

        index = 0;
        //failed = 0;
        //// Commit to DB
        //foreach (var objectsToInsert in queueObjects)
        //{
        //    // Start a transaction
        //    //using var transaction = context.Database.BeginTransaction();

        //    // We need to be-careful with the insert order, as we need to insert the parent album first
        //    // and since albums references assets, we need to insert assets first (Although this is not reflected in the model, but there is a circular dependency between albums and assets)

        //    context.Assets.AddRange(objectsToInsert.Assets);
        //    context.SaveChanges();

        //    // Insert all the objects
        //    context.Albums.AddRange(objectsToInsert.Albums);
        //    context.Tracks.AddRange(objectsToInsert.Tracks);

        //    // Commit the transaction
        //    //context.SaveChanges();
        //    //transaction.Commit();
        //    index++;
        //    Console.WriteLine($"[{index}/{queueObjects.Count}] Tracking {objectsToInsert.Albums.Count} Albums, {objectsToInsert.Tracks.Count} Tracks, {objectsToInsert.Assets.Count} Assets");

        //    if (index % 1000 == 0)
        //    {
        //        Console.WriteLine("Saving Changes");
        //        context.SaveChanges();
        //    }
        //}

        Console.WriteLine("Saving Changes");
        context.SaveChanges();
        var allHlsSegments = queueObjects.SelectMany(o => o.HlsSegments).ToList();
        var allHlsPlaylists = queueObjects.SelectMany(o => o.HlsPlaylists).ToList();

        Console.WriteLine("Inserting HLS Playlists");
        context.BulkInsert(allHlsPlaylists, progress: obj => Console.WriteLine($"PROGRESS: {obj.ToString()}"));

        Console.WriteLine("Inserting HLS Segments");
        context.BulkInsert(allHlsSegments, progress: obj => Console.WriteLine($"PROGRESS: {obj.ToString()}"));

        Console.WriteLine("Saving Changes");
        context.SaveChanges();

        Console.WriteLine("All Done");
    }
}