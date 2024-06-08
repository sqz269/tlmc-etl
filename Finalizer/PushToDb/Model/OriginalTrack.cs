using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

public class OriginalTrack
{
    [Key]
    [Required]
    public string Id { get; set; }

    [Column(TypeName = "jsonb")]
    public LocalizedField Title { get; set; }

    public string? ExternalReference { get; set; }

    public OriginalAlbum Album { get; set; }

    public List<Track> Tracks { get; set; }
}