namespace PushToDb.Model;

public enum CircleStatus {
    // Circle is active in touhou
    Active,

    // Currently Inactive, but may be active in the future
    Inactive,

    // Circle is disbanded, will not be active in the future
    Disbanded,

    // Circle is still active, but not in touhou
    Transfer,

    // Unknown, but queried
    Unknown,

    // Status not queried
    Unset
}

public class Circle
{
    public Guid Id { get; set; }

    public string Name { get; set; } = null!;
    public CircleStatus Status { get; set; }

    public DateOnly? Established { get; set; }

    public string? Country { get; set; }

    public List<string> Alias { get; set; } = [];

    public List<string> DataSource { get; set; } = [];

    // Stores the reference to the original TLMC directory (Raw name for the circle)
    public string? TlmcReference { get; set; }

    public List<CircleWebsite> Website { get; set; } = [];
}
