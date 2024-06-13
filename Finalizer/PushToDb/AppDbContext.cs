using Microsoft.EntityFrameworkCore;
using PushToDb.Model;

namespace PushToDb;

public class AppDbContext : DbContext
{
    public DbSet<Album> Albums { get; set; }
    public DbSet<Track> Tracks { get; set; }
    public DbSet<Circle> Circles { get; set; }
    public DbSet<CircleWebsite> CircleWebsites { get; set; }
    public DbSet<OriginalTrack> OriginalTracks { get; set; }
    public DbSet<OriginalAlbum> OriginalAlbums { get; set; }
    public DbSet<Asset> Assets { get; set; }
    public DbSet<HlsPlaylist> HlsPlaylist { get; set; }
    public DbSet<HlsSegment> HlsSegment { get; set; }
    public DbSet<Thumbnail> Thumbnails { get; set; }


    public AppDbContext(DbContextOptions<AppDbContext> opt) : base(opt)
    {
    }
    
    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        // Music Data Configuration
        modelBuilder.Entity<Thumbnail>().Navigation(t => t.Tiny).AutoInclude();
        modelBuilder.Entity<Thumbnail>().Navigation(t => t.Small).AutoInclude();
        modelBuilder.Entity<Thumbnail>().Navigation(t => t.Medium).AutoInclude();
        modelBuilder.Entity<Thumbnail>().Navigation(t => t.Large).AutoInclude();
        modelBuilder.Entity<Thumbnail>().Navigation(t => t.Original).AutoInclude();
        

        modelBuilder.Entity<Track>().Navigation(t => t.Original).AutoInclude();
        modelBuilder.Entity<Track>().Navigation(t => t.TrackFile).AutoInclude();
        modelBuilder.Entity<Track>().Navigation(t => t.Album).AutoInclude(false);

        modelBuilder.Entity<OriginalTrack>().Navigation(og => og.Album).AutoInclude();

        modelBuilder.Entity<Circle>()
            .Property(c => c.Status)
            .HasConversion(v => v.ToString(),
                v => (CircleStatus)Enum.Parse(typeof(CircleStatus), v));
        
        modelBuilder.Entity<Circle>().Navigation(t => t.Website).AutoInclude();

        modelBuilder.Entity<HlsPlaylist>()
            .Property(p => p.Type)
            .HasConversion(v => v.ToString(),
                v => Enum.Parse<HlsPlaylistType>(v));


        modelBuilder.Entity<Album>()
            .HasOne(a => a.Image)
            .WithOne()
            .HasForeignKey<Album>(a => a.ImageId);

        base.OnModelCreating(modelBuilder);
    }
}