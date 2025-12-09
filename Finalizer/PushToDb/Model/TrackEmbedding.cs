using Pgvector;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace PushToDb.Model;

public class TrackEmbedding
{
    [Key, ForeignKey(nameof(Track))]
    public Guid TrackId { get; set; }

    [Column(TypeName = "vector(1024)")]
    public Vector EmbeddingMean { get; set; }

    [Column(TypeName = "vector(2048)")]
    public Vector EmbeddingMeanMax { get; set; }

    public Track Track { get; set; }
}

