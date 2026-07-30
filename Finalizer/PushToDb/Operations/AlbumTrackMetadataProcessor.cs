using Microsoft.EntityFrameworkCore;
using Newtonsoft.Json;
using PushToDb.ExternalModel;
using PushToDb.Model;
using PushToDb.Utils;
using Sharprompt;

namespace PushToDb.Operations;

public static class AlbumTrackMetadataProcessor
{
    private const int AlbumsPerBatch = 500;

    public static void PushBasicAlbumAndTrackData(AppDbContext context)
    {
        var aggregatedFp = Prompt.Input<string>(
            "Enter path to assigned_megered.json",
            validators: [Validators.Required(), PathValidator.ValidateFilePath()]);
        var hlsFinalizedFp = Prompt.Input<string>(
            "Enter path to hls.finalized.output.json (v6 per-track shape)",
            validators: [Validators.Required(), PathValidator.ValidateFilePath()]);
        // Rows hold root-relative storage keys; this prefix is what gets stripped.
        var libraryRoot = Prompt.Input<string>(
            "Enter the library root prefix all source paths share",
            defaultValue: "/mnt/tlmc/TLMC v6",
            validators: [Validators.Required()]);

        Console.WriteLine("Loading Assignment Merged Data");
        var aggregated = JsonConvert.DeserializeObject<Dictionary<string, JAlbum>>(File.ReadAllText(aggregatedFp))!;

        Console.WriteLine("Loading Hls Finalized Data");
        var hlsFinalized = JsonConvert.DeserializeObject<Dictionary<string, HlsFinalizedTrack>>(File.ReadAllText(hlsFinalizedFp))!;

        // The v5 finalizer emitted a per-segment shape (master_playlist/medias);
        // deserializing it into the v6 model yields null track dirs. Fail here
        // with a usable message instead of NullReferences mid-load.
        if (hlsFinalized.Count > 0 && hlsFinalized.Values.First().TrackDir == null)
        {
            Console.WriteLine("ERROR: this looks like the old per-segment manifest shape. " +
                              "Re-run hls_finalizer.py (v6 emits track_dir/bitrates/has_dash) and retry.");
            return;
        }

        // Attribution only needs circle ids, not tracked entities; one snapshot up
        // front replaces a per-album query and survives ChangeTracker.Clear().
        var knownCircleIds = context.Circles.Select(c => c.Id).ToHashSet();

        var stats = new LoadStats();
        var index = 0;

        foreach (var (albumId, albumData) in aggregated)
        {
            InstantiateAlbum(context, albumData, hlsFinalized, libraryRoot, knownCircleIds, stats);
            stats.Releases++;
            index++;

            if (index % AlbumsPerBatch == 0)
            {
                // Cleared between batches: an ever-growing tracker made the old
                // loader quadratic.
                context.SaveChanges();
                context.ChangeTracker.Clear();
                Console.WriteLine($"[{index}/{aggregated.Count}] committed " +
                                  $"(tracks: {stats.Tracks}, no-media: {stats.TracksWithoutMedia})");
            }
        }

        context.SaveChanges();
        context.ChangeTracker.Clear();

        Console.WriteLine("All Done");
        Console.WriteLine(
            $"Releases: {stats.Releases}, Discs: {stats.Discs}, Tracks: {stats.Tracks} " +
            $"(without media: {stats.TracksWithoutMedia}), Assets: {stats.Assets}, " +
            $"Artworks: {stats.Artworks}, Credits: {stats.Credits}");
        if (stats.MissingCircleIds.Count > 0)
        {
            Console.WriteLine($"WARNING: {stats.MissingCircleIds.Count} attributed circle id(s) " +
                              "had no circle row; attribution for those was skipped:");
            foreach (var id in stats.MissingCircleIds.Take(20))
            {
                Console.WriteLine($"  {id}");
            }
        }

        if (stats.PathsOutsideRoot.Count > 0)
        {
            Console.WriteLine($"WARNING: {stats.PathsOutsideRoot.Count} path(s) were not under " +
                              $"'{libraryRoot}' and were skipped:");
            foreach (var path in stats.PathsOutsideRoot.Take(20))
            {
                Console.WriteLine($"  {path}");
            }
        }
    }

    private static void InstantiateAlbum(
        AppDbContext context,
        JAlbum albumData,
        Dictionary<string, HlsFinalizedTrack> hlsFinalized,
        string libraryRoot,
        HashSet<Guid> knownCircleIds,
        LoadStats stats)
    {
        var metadata = albumData.AlbumMetadata;
        var releaseId = Guid.Parse(metadata.AlbumId);

        var release = new Release
        {
            Id = releaseId,
            Name = metadata.AlbumName.AsLocalizedField(),
            ReleaseDate = metadata.ReleaseDate.TryGetDateOnly(),
            ReleaseConvention = metadata.ReleaseConvention.GetNonEmptyStringOrNull(),
            CatalogNumber = metadata.CatalogNumber.GetNonEmptyStringOrNull(),
            TlmcRootReference = [albumData.AlbumRoot],
        };
        context.Releases.Add(release);

        // Attribution, ordered as scraped. Collaborations arrive as multiple ids
        // here and become multiple rows — the old loader dropped them entirely.
        short ordinal = 0;
        foreach (var artistId in metadata.AlbumArtistIds.Select(Guid.Parse).Distinct())
        {
            if (!knownCircleIds.Contains(artistId))
            {
                stats.MissingCircleIds.Add(artistId);
                continue;
            }

            context.ReleaseCircles.Add(new ReleaseCircle
            {
                ReleaseId = releaseId,
                CircleId = artistId,
                Ordinal = ordinal++,
            });
        }

        // Assets, and the cover artwork if the scan pass designated one.
        Guid? thumbnailAssetId = null;
        foreach (var jAsset in albumData.Assets)
        {
            var storageKey = Relativize(jAsset.AssetPath, libraryRoot);
            if (storageKey == null)
            {
                stats.PathsOutsideRoot.Add(jAsset.AssetPath);
                continue;
            }

            var asset = new Asset
            {
                Id = Guid.Parse(jAsset.AssetId),
                Root = StorageRoot.Library,
                StorageKey = storageKey,
                Name = jAsset.AssetName,
            };
            context.Assets.Add(asset);
            stats.Assets++;

            if (jAsset.AssetPath == albumData.Thumbnail)
            {
                thumbnailAssetId = asset.Id;
            }
        }

        if (thumbnailAssetId is { } coverAssetId)
        {
            var artwork = new Artwork
            {
                Id = Guid.CreateVersion7(),
                SourceAssetId = coverAssetId,
            };
            context.Artworks.Add(artwork);
            release.ArtworkId = artwork.Id;
            stats.Artworks++;
        }

        // Discs: one row each, always — no disc-0 sentinel, no id reuse. Disc
        // numbers are sanitised to a dense 1..N when the metadata's are unusable,
        // because the schema enforces uniqueness per release.
        var discNumbersSeen = new HashSet<short>();
        var discOrdinal = (short)0;
        foreach (var jDisc in albumData.Discs.Values)
        {
            discOrdinal++;
            var discNumber = (short)jDisc.DiscNumber;
            if (discNumber < 1 || !discNumbersSeen.Add(discNumber))
            {
                discNumber = discOrdinal;
                while (!discNumbersSeen.Add(discNumber))
                {
                    discNumber++;
                }
            }

            var disc = new Disc
            {
                Id = Guid.Parse(jDisc.DiscId),
                ReleaseId = releaseId,
                DiscNumber = discNumber,
                Name = jDisc.DiscName.GetNonEmptyStringOrNull(),
            };
            context.Discs.Add(disc);
            stats.Discs++;

            InstantiateTracks(context, jDisc, disc.Id, hlsFinalized, libraryRoot, stats);
        }
    }

    private static void InstantiateTracks(
        AppDbContext context,
        JDisc jDisc,
        Guid discId,
        Dictionary<string, HlsFinalizedTrack> hlsFinalized,
        string libraryRoot,
        LoadStats stats)
    {
        var trackNumbersSeen = new HashSet<short>();
        var trackOrdinal = (short)0;

        foreach (var jTrack in jDisc.Tracks)
        {
            trackOrdinal++;
            var trackMetadata = jTrack.TrackMetadata;
            var trackId = Guid.Parse(trackMetadata.TrackId);

            var trackNumber = (short)trackMetadata.Track;
            if (trackNumber < 1 || !trackNumbersSeen.Add(trackNumber))
            {
                trackNumber = trackOrdinal;
                while (!trackNumbersSeen.Add(trackNumber))
                {
                    trackNumber++;
                }
            }

            var track = new Track
            {
                Id = trackId,
                DiscId = discId,
                TrackNumber = trackNumber,
                Name = trackMetadata.Title.AsLocalizedField(),
            };

            // Media is not a precondition for the row: 40 upstream-broken files,
            // partial transfers and CJK publish failures still deserve catalogue
            // entries that browse and search — they just cannot play.
            if (hlsFinalized.TryGetValue(jTrack.TrackPath, out var hls))
            {
                track.MediaKey = Relativize(hls.TrackDir, libraryRoot);
                if (track.MediaKey == null)
                {
                    stats.PathsOutsideRoot.Add(hls.TrackDir);
                    stats.TracksWithoutMedia++;
                }
                else
                {
                    track.HlsBitrates = hls.Bitrates.OrderBy(b => b).ToList();
                    track.HasDash = hls.HasDash;
                }
            }
            else
            {
                stats.TracksWithoutMedia++;
            }

            context.Tracks.Add(track);
            stats.Tracks++;

            // Verbatim credits, split on the source's ", " convention, order kept.
            var creditOrdinal = (short)0;
            foreach (var name in trackMetadata.Artist.Split(", ")
                         .Select(s => s.Trim())
                         .Where(s => s.Length > 0))
            {
                context.TrackCredits.Add(new TrackCredit
                {
                    TrackId = trackId,
                    Role = CreditRole.Staff,
                    Ordinal = creditOrdinal++,
                    CreditName = name,
                });
                stats.Credits++;
            }
        }
    }

    /// <summary>
    /// Absolute path → forward-slashed root-relative storage key, or null when the
    /// path is not under the root. No prefix substitution ever lands in a row.
    /// </summary>
    private static string? Relativize(string absolutePath, string libraryRoot)
    {
        var normalized = absolutePath.Replace('\\', '/');
        var root = libraryRoot.Replace('\\', '/').TrimEnd('/');

        if (!normalized.StartsWith(root + '/', StringComparison.Ordinal))
        {
            return null;
        }

        var key = normalized[(root.Length + 1)..].TrimStart('/');
        return key.Length == 0 ? null : key;
    }

    private class LoadStats
    {
        public int Releases;
        public int Discs;
        public int Tracks;
        public int TracksWithoutMedia;
        public int Assets;
        public int Artworks;
        public int Credits;
        public HashSet<Guid> MissingCircleIds { get; } = [];
        public List<string> PathsOutsideRoot { get; } = [];
    }
}
