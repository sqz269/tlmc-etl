using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Newtonsoft.Json;

namespace PushToDb.Model;

public class Ruby
{
    public required int Index { get; set; }
    public required int Length { get; set; }
    public required string Text { get; set; }
}

public class LyricsText
{
    public required string Lang { get; set; }
    public required string Text { get; set; }
    public List<Ruby> Ruby { get; set; } = [];
}

public class LyricsLine
{
    // Index MUST be specified, if timespan is specified also
    // then SHOULD be Index(A) > Index(B) given TimeSpan(A) > TimeSpan(B)
    // however, this is not necessary
    // Index specifies the order of the lines if
    // time was not specified, otherwise, time should always
    // be prioritized
    public required int Index { get; set; }
    public TimeSpan? Time { get; set; }
    public required List<LyricsText> Blocks { get; set; }
}

public class LyricsVariant
{
    public string? Variant { get; set; }
    public required List<LyricsLine> Lines { get; set; } = [];
}

public class Lyrics
{
    [Key]
    public required Guid Id { get; set; }

    [Column(TypeName = "jsonb")]
    public required List<LyricsVariant> Variants { get; set; }

    public string? ReferenceUrl { get; set; }
}