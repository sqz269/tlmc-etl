using System.Drawing;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml;
using Microsoft.VisualBasic.FileIO;
using UtfUnknown.Core.Analyzers.Japanese;

namespace CueSplitter;

public struct TrackProcess
{
    public string TrackName { get; set; }
    public string TrackNumber { get; set; }
    public string Performer { get; set; }
    public string? Begin { get; set; }
    public string Duration { get; set; }
}

public struct AlbumProcess
{
    public string AlbumName { get; set; }
    public string Performer { get; set; }
    public string AudioFilePath { get; set; }
    public string AudioFilePathGuessed { get; set; }
    public List<string> AudioFilePathGuessedCandidate { get; set; }
    public string CueFilePath { get; set; }
    public string Root { get; set; }
    public List<TrackProcess> Tracks { get; set; }
    public bool Invalid { get; set; }
}

public static class CueSplit
{
    public static Dictionary<char, char> REPLACE_CHARS = new()
    {
        {'/', '／'},
        {'\\', '＼'},
        {':', '：'},
        {'*', '＊'},
        {'?', '？'},
        {'\"', '＂'},
        {'<', '＜'},
        {'>', '＞'},
        {'|', '｜'}
    };

    private static string MkFileName(Track track, CueSheet origin)
    {
        var sb = new List<string>();

        sb.Add($"({track.TrackNumber:00})");

        if (!string.IsNullOrWhiteSpace(track.Performer))
        {
            sb.Add($"[{track.Performer}]");
        }
        else
        {
            sb.Add($"[{origin.Performer}]");
        }

        sb.Add($"{track.Title}.flac");

        // The file names could contain / and \, which may cause issues
        // so we need to replace the / and \ characters to full width part to avoid path issues
        var str = string.Join(' ', sb);
        foreach (var (key, value) in REPLACE_CHARS)
        {
            str = str.Replace(key, value);
        }

        return str;
    }

    private static List<string>? TryFindCueTrack(string root, string cuePath, CueSheet origin)
    {
        var excludeExtensions = new List<string>
        {
            ".cue",
            ".log",
            ".txt"
        };

        var reg = new Regex("(?:.+ - )?(.+)\\..+", RegexOptions.Compiled | RegexOptions.IgnoreCase);

        // if there is only one flac file in the root directory.
        // return that file
        var dir = new DirectoryInfo(root);
        var flacs = new List<FileInfo>();

        var cueCharacteristic = reg.Match(Path.GetFileName(cuePath)).Groups[1].Value;
        var characteristic = reg.Match(origin.Tracks[0].DataFile.Filename).Groups[1].Value;

        foreach (var fileInfo in dir.GetFiles())
        {
            if (excludeExtensions.Any(s => fileInfo.Name.EndsWith(s)))
            {
                continue;
            }

            var characteristicFile = reg.Match(fileInfo.Name).Groups[1].Value;

            if (characteristic.Equals(characteristicFile) || cueCharacteristic.Equals(characteristicFile))
            {
                flacs.Add(fileInfo);
                continue;
            }

            if (fileInfo.Name.EndsWith(".flac"))
            {
                flacs.Add(fileInfo);
            }
        }

        return flacs.Count switch
        {
            1 => flacs.Select(f => f.FullName).ToList(),
            > 1 =>
                // return the file with the highest size
                flacs.OrderByDescending(sel => sel.Length).Select(f => f.FullName).ToList(),
            _ => null
        };
    }

    private static TrackProcess MkSplitArgs(Track track, CueSheet origin, Index begin, Index? end, string root)
    {
        var outpath = Path.Combine(root, MkFileName(track, origin));

        var trackProcess = new TrackProcess()
        {
            TrackName = MkFileName(track, origin),
            TrackNumber = track.TrackNumber.ToString(),
            Performer = track.Performer,
            Begin = begin.ToTimeSpan().ToString(),
            Duration = end?.Duration(begin).ToString() ?? string.Empty
        };

        return trackProcess;
    }

    private static AlbumProcess Split(CueSheet sheet, string cuePath, string root)
    {
        // only the first file have data file prop
        var filePath = Path.Combine(root, sheet.Tracks[0].DataFile.Filename);
        string? guessedPath = null;
        List<string>? guessedCandidate = new List<string>();
        var invalid = false;

        if (!File.Exists(filePath))
        {
            guessedCandidate = TryFindCueTrack(root, cuePath, sheet);

            if (guessedCandidate == null || guessedCandidate?.Count == 0)
            {
                invalid = true;
            }
            else
            {
                guessedPath = guessedCandidate[0];
            }
        }

        var album = new AlbumProcess()
        {
            Root = root,
            AlbumName = sheet.Title,
            Performer = sheet.Performer,
            AudioFilePath = filePath,
            AudioFilePathGuessed = guessedPath,
            AudioFilePathGuessedCandidate = guessedCandidate,
            CueFilePath = cuePath,
            Tracks = new List<TrackProcess>(),
            Invalid = invalid
        };

        for (var i = 0; i < sheet.Tracks.Length; i++)
        {
            var track = sheet.Tracks[i];
            Index start;
            Index? end = null;
            // Always take the first index as the start
            // Same as MPV strategy:
            // https://github.com/mpv-player/mpv/blob/375076578f4c1c450ecf0b60de6290ad9942ddfc/demux/demux_mkv.c#L852
            start = track.Indices[0];

            // While we haven't reached end of tracks
            if (i + 1 < sheet.Tracks.Length)
            {
                var next = sheet.Tracks[i + 1];

                end = next.Indices[0];
            }

            album.Tracks.Add(MkSplitArgs(track, sheet, start, end, root));
        }

        return album;
    }

    public static string SplitCue(string root, string cuePath)
    {
        var cueFile = FileUtils.ReadFileAutoEncoding(cuePath);
        var cue = new CueSheet(cueFile, new char[] { '\r', '\n' });

        var p = Split(cue, cuePath, root);
        return JsonSerializer.Serialize(p);
    }

    private static AlbumProcess SplitFromEmbeddedCue(string flacPath, CueSheet cueSheet)
    {
        // get flac's Parent dir
        DirectoryInfo dirInfo = new(flacPath);
        string root = dirInfo.Parent.FullName;

        // only the first file have data file prop
        var album = new AlbumProcess()
        {
            Root = root,
            AlbumName = cueSheet.Title,
            Performer = cueSheet.Performer,
            AudioFilePath = flacPath,
            AudioFilePathGuessed = "",
            AudioFilePathGuessedCandidate = new(),
            CueFilePath = "<EMBEDDED>",
            Tracks = new List<TrackProcess>(),
            Invalid = false
        };

        for (var i = 0; i < cueSheet.Tracks.Length; i++)
        {
            var track = cueSheet.Tracks[i];
            Index start;
            Index? end = null;
            // Always take the first index as the start
            // Same as MPV strategy:
            // https://github.com/mpv-player/mpv/blob/375076578f4c1c450ecf0b60de6290ad9942ddfc/demux/demux_mkv.c#L852
            start = track.Indices[0];

            // While we haven't reached end of tracks
            if (i + 1 < cueSheet.Tracks.Length)
            {
                var next = cueSheet.Tracks[i + 1];

                end = next.Indices[0];
            }

            album.Tracks.Add(MkSplitArgs(track, cueSheet, start, end, root));
        }

        return album;
    }

    public static string SplitCueWithEmbedCueSheet(string flac, string cueSheet)
    {
        var cue = new CueSheet(cueSheet, new char[] { '\r', '\n' });

        var p = SplitFromEmbeddedCue(flac, cue);
        return JsonSerializer.Serialize(p);
    }
}