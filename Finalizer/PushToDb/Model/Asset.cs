using System.ComponentModel.DataAnnotations;

namespace PushToDb.Model;

public class Asset
{
    [Key]
    [Required]
    public Guid Id { get; set; }
    [Required]
    public string Name { get; set; }
    [Required]
    public string Path { get; set; }
    public string? Mime { get; set; }
    public long Size { get; set; }
}