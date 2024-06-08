namespace PushToDb.Model;

public class Thumbnail
{
    public Guid Id { get; set; }

    public Asset Original { get; set; }
    // 350 x 350
    public Asset Large { get; set; }
    // 250 x 250
    public Asset Medium { get; set; }
    // 125 x 125
    public Asset Small { get; set; }
    // 50 x 50
    public Asset Tiny { get; set; }

    public List<string> Colors { get; set; } = [];
}