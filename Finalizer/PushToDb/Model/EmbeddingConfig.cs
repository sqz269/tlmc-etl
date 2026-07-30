namespace PushToDb.Model;

/// <summary>
/// Single-row provenance stamp, written in the same transaction as the embedding
/// and similar_track loads. What the API reports as the similarity basis.
/// </summary>
public class EmbeddingConfig
{
    /// <summary>Always true; CHECK (id) makes this a one-row table.</summary>
    public bool Id { get; set; } = true;

    /// <summary>Model + chunking + layer mix, e.g. 'mert-v1-330m/win6s-hop4s/last4'.</summary>
    public string Model { get; set; } = null!;

    public DateTime LoadedAt { get; set; }

    public int TrackCount { get; set; }
}
