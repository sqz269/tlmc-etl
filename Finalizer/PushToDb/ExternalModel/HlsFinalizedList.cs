using Newtonsoft.Json;

namespace PushToDb.ExternalModel;

/// <summary>
/// One entry per track in hls.finalized.output.json, keyed by source audio path.
/// v6 shape: per-track facts only — the per-segment inventory is gone, because the
/// on-disk layout is a convention (SCHEMA-V6.md section 3). The manifest survives
/// at all because collision-renamed directories (`stem [ext]`) make the track dir
/// non-derivable from metadata alone.
/// </summary>
public class HlsFinalizedTrack
{
    /// <summary>Absolute track directory; the loader relativizes it into media_key.</summary>
    [JsonProperty("track_dir")]
    public string TrackDir { get; set; } = null!;

    /// <summary>Available rungs, e.g. [128, 192, 256, 320].</summary>
    [JsonProperty("bitrates")]
    public List<short> Bitrates { get; set; } = [];

    [JsonProperty("has_dash")]
    public bool HasDash { get; set; }
}
