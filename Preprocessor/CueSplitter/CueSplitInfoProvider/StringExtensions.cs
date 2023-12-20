using System.Security.Cryptography;
using System.Text;

namespace CueSplitter;

public static class StringExtensions
{
    public static string HashSHA1(this string value)
    {
        var sha1 = SHA1.Create();
        var inputBytes = Encoding.ASCII.GetBytes(value);
        var hash = sha1.ComputeHash(inputBytes);
        var sb = new StringBuilder();
        for (var i = 0; i < hash.Length; i++)
        {
            sb.Append(hash[i].ToString("X2"));
        }
        return sb.ToString();
    }

    public static string GetSha1Sig(this string val)
    {
        return val.HashSHA1().Substring(0, 5);
    }
}