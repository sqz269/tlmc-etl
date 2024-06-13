namespace PushToDb.ExternalModel;

using System;
using System.Collections.Generic;
using Newtonsoft.Json;

public class JTrackMetadata
{
    [JsonProperty("artist")]
    public string Artist { get; set; }

    [JsonProperty("title")]
    public string Title { get; set; }

    [JsonProperty("track")]
    public int Track { get; set; }

    [JsonProperty(nameof(TrackId))]
    public string TrackId { get; set; }
}

public class JTrack
{
    [JsonProperty(nameof(TrackPath))]
    public string TrackPath { get; set; }

    [JsonProperty(nameof(TrackMetadata))]
    public JTrackMetadata TrackMetadata { get; set; }
}

public class JDisc
{
    [JsonProperty(nameof(DiscNumber))]
    public int DiscNumber { get; set; }

    [JsonProperty(nameof(DiscName))]
    public string DiscName { get; set; }

    [JsonProperty(nameof(Tracks))]
    public List<JTrack> Tracks { get; set; }

    [JsonProperty(nameof(DiscId))]
    public string DiscId { get; set; }
}

public class JAsset
{
    [JsonProperty(nameof(AssetPath))]
    public string AssetPath { get; set; }

    [JsonProperty(nameof(AssetName))]
    public string AssetName { get; set; }

    [JsonProperty(nameof(AssetId))]
    public string AssetId { get; set; }
}

public class JAlbumMetadata
{
    [JsonProperty(nameof(AlbumName))]
    public string AlbumName { get; set; }

    [JsonProperty(nameof(AlbumArtist))]
    public string AlbumArtist { get; set; }

    [JsonProperty(nameof(ReleaseDate))]
    public string ReleaseDate { get; set; }

    [JsonProperty(nameof(CatalogNumber))]
    public string CatalogNumber { get; set; }

    [JsonProperty(nameof(ReleaseConvention))]
    public string ReleaseConvention { get; set; }

    [JsonProperty(nameof(AlbumArtistIds))]
    public List<string> AlbumArtistIds { get; set; }

    [JsonProperty(nameof(AlbumId))]
    public string AlbumId { get; set; }
}

public class JAlbum
{
    [JsonProperty(nameof(AlbumRoot))]
    public string AlbumRoot { get; set; }

    [JsonProperty(nameof(Discs))]
    public Dictionary<string, JDisc> Discs { get; set; }

    [JsonProperty(nameof(Assets))]
    public List<JAsset> Assets { get; set; }

    [JsonProperty(nameof(Thumbnail))]
    public string Thumbnail { get; set; }

    [JsonProperty(nameof(UnidentifiedTracks))]
    public List<string> UnidentifiedTracks { get; set; }

    [JsonProperty(nameof(HasAssetOfInterest))]
    public bool HasAssetOfInterest { get; set; }

    [JsonProperty(nameof(NeedsManualReview))]
    public bool NeedsManualReview { get; set; }

    [JsonProperty(nameof(NeedsManualReviewReason))]
    public List<string> NeedsManualReviewReason { get; set; }

    [JsonProperty(nameof(AlbumMetadata))]
    public JAlbumMetadata AlbumMetadata { get; set; }
}
