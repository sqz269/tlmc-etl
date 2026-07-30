namespace PushToDb.Model;

public class Disc
{
    public Guid Id { get; set; }

    public Guid ReleaseId { get; set; }

    /// <summary>1-based; unique per release (enforced by the schema).</summary>
    public short DiscNumber { get; set; }

    public string? Name { get; set; }

    public List<Track> Tracks { get; set; } = [];
}
