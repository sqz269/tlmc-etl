using System.ComponentModel.DataAnnotations;

namespace PushToDb.Model;

public enum HlsPlaylistType
{
    Master,
    Media
}

public class HlsPlaylist
{
    [Key]
    public Guid Id { get; set; }
    
    public HlsPlaylistType Type { get; set; }
    
    // bitrate may be null when Type = Master
    public int? Bitrate { get; set; }
    
    public string HlsPlaylistPath { get; set; }

    public List<HlsSegment> Segments { get; set; }
    
    public Guid TrackId { get; set; }
    public Track Track { get; set; }
}