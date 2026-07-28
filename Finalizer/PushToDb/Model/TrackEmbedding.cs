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

    // halfvec to match the schema owned by TlmcPlayerBackend (migration
    // EmbeddingHalfvecAndHnsw): vector(2048) exceeds pgvector's 2000-dim
    // index limit, halfvec is indexable up to 4000
    [Column(TypeName = "halfvec(2048)")]
    public HalfVector EmbeddingMeanMax { get; set; }

    public Track Track { get; set; }
}

