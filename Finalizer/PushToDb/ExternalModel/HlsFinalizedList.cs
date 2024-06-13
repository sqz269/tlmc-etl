using Newtonsoft.Json;

namespace PushToDb.ExternalModel;

public class MediaPlaylistInfo
{
    [JsonProperty("segments")]
    // First string is the path to the segment, second int is the segment index
    public Dictionary<string, int> Segments { get; set; }

    [JsonProperty("playlist")]
    // Points to the playlist.m3u8 file
    public string Playlist { get; set; }
}

public class HlsTrack
{
    [JsonProperty("master_playlist")]
    public string MasterPlaylist { get; set; }

    [JsonProperty("medias")]
    // First string is the quality, e.g. 320k, 128k
    public Dictionary<string, MediaPlaylistInfo> MediaPlaylist { get; set; }
}