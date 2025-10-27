using System.ComponentModel.DataAnnotations;
using Sharprompt;

namespace PushToDb.UserOptions;

public enum UserOptionDataOptions
{
    [Display(Name = "Artist/Circle basic metadata")]
    CircleBasicMetadata,
    [Display(Name = "Albums and Track basic metadata (With HLS Postprocessing)")]
    AlbumTrackBasicMetadata,

    [Display(Name = "Thwiki Sourced Extended Artist/Circle metadata")]
    ThwikiExtendedArtistCircleMetadata,
    [Display(Name = "Thwiki Sourced Extended Album/Track metadata")]
    ThwikiExtendedAlbumTrackMetadata,
    [Display(Name = "Thwiki Sourced Lyrics Data")]
    ThwikiLyricsData,

    [Display(Name = "MPEG DASH Repackaged Playlists")]
    MpegDashPlaylists,
}
