using System.ComponentModel.DataAnnotations;

namespace PushToDb.Model;

public class HlsSegment
{
    [Key]
    public Guid Id { get; set; }
    
    public int Index { get; set; }
    
    public string Name { get; set; }
    
    public string Path { get; set; }

    public Guid HlsPlaylistId { get; set; }
    public HlsPlaylist HlsPlaylist { get; set; }
}