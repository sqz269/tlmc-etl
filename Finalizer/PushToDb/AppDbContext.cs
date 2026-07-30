using Microsoft.EntityFrameworkCore;
using PushToDb.Model;

namespace PushToDb;

/// <summary>
/// Loader-side view of the v6 schema. TlmcPlayerBackend owns the DDL (its
/// InitialV6 migration); this context maps only the tables and columns the ETL
/// writes, with the same singular snake_case names.
/// </summary>
public class AppDbContext : DbContext
{
    public DbSet<Release> Releases { get; set; }
    public DbSet<Disc> Discs { get; set; }
    public DbSet<Track> Tracks { get; set; }
    public DbSet<ReleaseCircle> ReleaseCircles { get; set; }
    public DbSet<TrackCredit> TrackCredits { get; set; }
    public DbSet<Circle> Circles { get; set; }
    public DbSet<CircleWebsite> CircleWebsites { get; set; }
    public DbSet<Asset> Assets { get; set; }
    public DbSet<Artwork> Artworks { get; set; }
    public DbSet<TrackEmbedding> TrackEmbeddings { get; set; }
    public DbSet<EmbeddingConfig> EmbeddingConfigs { get; set; }

    public AppDbContext(DbContextOptions<AppDbContext> opt) : base(opt)
    {
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Release>().ToTable("release");

        var disc = modelBuilder.Entity<Disc>();
        disc.ToTable("disc");
        disc.HasOne<Release>()
            .WithMany(r => r.Discs)
            .HasForeignKey(d => d.ReleaseId);

        var track = modelBuilder.Entity<Track>();
        track.ToTable("track");
        track.HasOne<Disc>()
            .WithMany(d => d.Tracks)
            .HasForeignKey(t => t.DiscId);

        var releaseCircle = modelBuilder.Entity<ReleaseCircle>();
        releaseCircle.ToTable("release_circle");
        releaseCircle.HasKey(rc => new { rc.ReleaseId, rc.CircleId });

        var trackCredit = modelBuilder.Entity<TrackCredit>();
        trackCredit.ToTable("track_credit");
        trackCredit.HasKey(tc => new { tc.TrackId, tc.Role, tc.Ordinal });

        var circle = modelBuilder.Entity<Circle>();
        circle.ToTable("circle");
        circle.Property(c => c.Status)
            .HasConversion(v => v.ToString(),
                v => (CircleStatus)Enum.Parse(typeof(CircleStatus), v));
        circle.Navigation(t => t.Website).AutoInclude();

        modelBuilder.Entity<CircleWebsite>().ToTable("circle_website");

        modelBuilder.Entity<Asset>().ToTable("asset");

        modelBuilder.Entity<Artwork>().ToTable("artwork");

        var trackEmbedding = modelBuilder.Entity<TrackEmbedding>();
        trackEmbedding.ToTable("track_embedding");
        trackEmbedding.HasKey(e => e.TrackId);

        var embeddingConfig = modelBuilder.Entity<EmbeddingConfig>();
        embeddingConfig.ToTable("embedding_config");
        embeddingConfig.HasKey(c => c.Id);
        embeddingConfig.Property(c => c.Id).ValueGeneratedNever();

        base.OnModelCreating(modelBuilder);
    }
}
