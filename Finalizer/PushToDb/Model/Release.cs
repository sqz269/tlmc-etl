using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

// Mirrors TlmcPlayerBackend's v6 schema (Docs/SCHEMA-V6.md in tlmc-player), which
// owns the DDL. This loader maps only the columns it writes -- generated columns
// (name_sort) and defaulted timestamps are deliberately absent.

public class Release
{
    public Guid Id { get; set; }

    [Column(TypeName = "jsonb")]
    public LocalizedField Name { get; set; } = null!;

    public DateOnly? ReleaseDate { get; set; }

    public string? ReleaseConvention { get; set; }

    public string? CatalogNumber { get; set; }

    public List<string> Websites { get; set; } = [];

    public List<string> DataSources { get; set; } = [];

    public List<string> TlmcRootReference { get; set; } = [];

    public Guid? ArtworkId { get; set; }

    public List<Disc> Discs { get; set; } = [];
}

public class ReleaseCircle
{
    public Guid ReleaseId { get; set; }
    public Guid CircleId { get; set; }
    public short Ordinal { get; set; }
}
