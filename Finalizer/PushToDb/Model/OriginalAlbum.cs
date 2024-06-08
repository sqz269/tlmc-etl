using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

public class OriginalAlbum
{
    [Key]
    [Required]
    public string Id { get; set; }

    [Required]
    public string Type { get; set; }

    [Required]
    [Column(TypeName = "jsonb")]
    public LocalizedField FullName { get; set; }

    [Required]
    [Column(TypeName = "jsonb")]
    public LocalizedField ShortName { get; set; }

    public string ExternalReference { get; set; }
    
    public List<OriginalTrack> Tracks { get; set; } = new();
}