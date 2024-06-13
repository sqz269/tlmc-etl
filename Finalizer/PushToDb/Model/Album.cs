using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

public class Album
{
    [Key]
    public Guid Id { get; set; }

    [Required]
    [Column(TypeName = "jsonb")]
    public LocalizedField Name { get; set; } = new();

    [Column(TypeName = "date")]
    public DateTime? ReleaseDate { get; set; }

    public string? ReleaseConvention { get; set; }

    public string? CatalogNumber { get; set; }

    [Required]
    public int? NumberOfDiscs { get; set; }

    /// <summary>
    /// Denotes a Disc number in a specific album
    /// NOTE: Disc0 is reserved as a 
    /// </summary>
    [Required]
    public int? DiscNumber { get; set; }

    public string? DiscName { get; set; }

    public List<string>? Website { get; set; } = new();

    [Required]
    public List<Circle>? AlbumArtist { get; set; } = new();

    public List<string>? DataSource { get; set; } = new();

    public List<Track>? Tracks { get; set; } = new();

    public Album? ParentAlbum { get; set; }

    public List<Album>? ChildAlbums { get; set; } = new();

    public Guid? ImageId { get; set; }
    public Asset? Image { get; set; }

    public Thumbnail? Thumbnail { get; set; }

    public List<Asset> OtherFiles { get; set; } = new();
}