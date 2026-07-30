namespace PushToDb.Model;

public enum StorageRoot
{
    Library,
    Thumbnail,
    Generated,
}

public class Asset
{
    public Guid Id { get; set; }

    public StorageRoot Root { get; set; }

    /// <summary>Root-relative, forward-slashed, no leading slash — never an absolute path.</summary>
    public string StorageKey { get; set; } = null!;

    public string Name { get; set; } = null!;

    public string? Mime { get; set; }

    public long ByteSize { get; set; }

    public string? ContentHash { get; set; }
}
