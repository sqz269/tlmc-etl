using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using PushToDb.Model;

namespace PushToDb.Utils;

public static class StringExtensions
{
    public static bool IsStringAllEnglishAscii(this string str)
    {
        return str.All(c => c >= 0x20 && c <= 0x7E);
    }

    public static string? GetNonEmptyStringOrNull(this string? str)
    {
        return string.IsNullOrWhiteSpace(str) ? null : str;
    }

    public static DateTime? TryGetDateTime(this string? dateString)
    {
        if (string.IsNullOrWhiteSpace(dateString))
        {
            return null;
        }

        if (DateTime.TryParse(dateString, out var date))
        {
            return date;
        }

        return null;
    }

    public static LocalizedField AsLocalizedField(this string str)
    {
        return new LocalizedField()
        {
            Default = str,
            Jp = str,
            Zh = null,
            En = str.IsStringAllEnglishAscii() ? str : null
        };
    }
}
