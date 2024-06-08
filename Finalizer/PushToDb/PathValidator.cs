using System.ComponentModel.DataAnnotations;

namespace PushToDb;

public static class PathValidator
{
    public static Func<object, ValidationResult> ValidateFilePath(string errorMessage = null)
    {
        return (Func<object, ValidationResult>) (input =>
        {
            if (input is string str && System.IO.File.Exists(str))
            {
                return ValidationResult.Success;
            }
            return new ValidationResult(errorMessage ?? "File does not exist");
        });
    }
}