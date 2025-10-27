using System.ComponentModel.DataAnnotations;

namespace PushToDb.Model;

public class DashPlaylist
{
    [Key]
    public Guid Id { get; set; }
    public string DashPlaylistPath { get; set; }
    public Guid TrackId { get; set; }
    public Track Track { get; set; }
}