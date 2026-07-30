using System.ComponentModel.DataAnnotations;

namespace PushToDb.UserOptions;

public enum UserOptionDataOptions
{
    [Display(Name = "Artist/Circle basic metadata")]
    CircleBasicMetadata,
    [Display(Name = "Albums and Track basic metadata (With HLS Postprocessing)")]
    AlbumTrackBasicMetadata,
    [Display(Name = "Track Embedding Data (stamps embedding_config)")]
    TrackEmbeddingData,
    [Display(Name = "Similar Track Data (precompute shard CSVs)")]
    SimilarTrackData,
}
