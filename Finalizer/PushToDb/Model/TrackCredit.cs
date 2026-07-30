namespace PushToDb.Model;

public enum CreditRole
{
    Arranger,
    Vocalist,
    Lyricist,
    Performer,
    Staff,
}

/// <summary>
/// Verbatim scraped credit, one row per name per role, ordered. There is nothing to
/// resolve at load time — a load can never fail because a name was ambiguous.
/// </summary>
public class TrackCredit
{
    public Guid TrackId { get; set; }
    public CreditRole Role { get; set; }
    public short Ordinal { get; set; }
    public string CreditName { get; set; } = null!;
}
