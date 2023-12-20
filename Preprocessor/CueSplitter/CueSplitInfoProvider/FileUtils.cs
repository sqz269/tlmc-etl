using System.Text;
using UtfUnknown;

namespace CueSplitter;

public static class FileUtils
{
    public static string ReadFileAutoEncoding(string file)
    {
        using var stream = new FileStream(file, FileMode.Open, FileAccess.Read);

        var buffer = new byte[stream.Length];

        stream.Read(buffer, 0, buffer.Length);

        var result = CharsetDetector.DetectFromBytes(buffer);
        if (result.Detected != null)
        {
            return result.Detected.Encoding.GetString(buffer);
        }
        else
        {
            return Encoding.UTF8.GetString(buffer);
        }
    }
}