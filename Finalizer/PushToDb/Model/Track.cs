using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

public class Track
{
    [Key]
    [Required]
    public Guid Id { get; set; }

    [Required]
    [Column(TypeName = "jsonb")]
    public LocalizedField Name { get; set; }

    [Required]
    public int Index { get; set; }

    [Required]
    public int Disc { get; set; }

    public TimeSpan? Duration { get; set; }

    public List<string> Genre { get; set; } = new();

    public List<string> Staff { get; set; } = new();

    public List<string> Arrangement { get; set; } = new();

    public List<string> Vocalist { get; set; } = new();

    public List<string> Lyricist { get; set; } = new();

    public bool? OriginalNonTouhou { get; set; }
    
    public Album Album { get; set; }

    public List<OriginalTrack> Original { get; set; } = new();

    public Asset? TrackFile { get; set; }

    public TrackEmbedding? Embedding { get; set; }

    [ForeignKey("LyricsId")]
    public Lyrics? Lyrics { get; set; }
    public Guid? LyricsId { get; set; }
}