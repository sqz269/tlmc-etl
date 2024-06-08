namespace PushToDb.Model;

public interface ILyricsLineAnnotation
{
    public string Type { get; }
}

public class LyricsRubyAnnotation : ILyricsLineAnnotation
{
    public string Type { get; private set; } = "ruby";
    public string Text { get; set; }
    public int Start { get; set; }
    public int End { get; set; }
    public string Ruby { get; set; }
}

public class LyricsAnnotatedLine
{
    public string Language { get; set; }
    public string Text { get; set; }
    public List<ILyricsLineAnnotation> Annotations { get; set; }
}

public class LyricsTimeInstant
{
    public TimeSpan? Instant { get; set; }
    public List<LyricsAnnotatedLine> Line { get; set; }
}

public class LyricsDocument
{
    public string Title { get; set; }
    public List<LyricsTimeInstant> Lines { get; set; }
}

public class LyricsCollection
{
    public List<LyricsDocument> Documents { get; set; }
}