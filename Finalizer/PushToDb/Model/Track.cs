using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

public class Track
{
    public Guid Id { get; set; }

    public Guid DiscId { get; set; }

    /// <summary>1-based; unique per disc (enforced by the schema).</summary>
    public short TrackNumber { get; set; }

    [Column(TypeName = "jsonb")]
    public LocalizedField Name { get; set; } = null!;

    public TimeSpan? Duration { get; set; }

    public bool? OriginalNonTouhou { get; set; }

    /// <summary>
    /// Root-relative track directory in the library storage root. NULL is a valid
    /// state: the track exists in the catalogue but has no playable media — media
    /// is no longer a precondition for a row.
    /// </summary>
    public string? MediaKey { get; set; }

    public List<short> HlsBitrates { get; set; } = [];

    public bool HasDash { get; set; }

    public Guid? SourceAssetId { get; set; }

    public Guid? LyricsId { get; set; }
}
