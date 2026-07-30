using System.ComponentModel.DataAnnotations.Schema;
using Pgvector;

namespace PushToDb.Model;

public class TrackEmbedding
{
    public Guid TrackId { get; set; }

    /// <summary>'mean' pooling.</summary>
    [Column(TypeName = "vector(1024)")]
    public Vector EmbeddingMean { get; set; } = null!;

    // halfvec to match the schema owned by TlmcPlayerBackend: pgvector's HNSW
    // caps at 2000 dims for vector but 4000 for halfvec, and fp16 is ample
    // precision for a recall stage.
    /// <summary>'mean+max' pooling.</summary>
    [Column(TypeName = "halfvec(2048)")]
    public HalfVector EmbeddingMeanMax { get; set; } = null!;
}
