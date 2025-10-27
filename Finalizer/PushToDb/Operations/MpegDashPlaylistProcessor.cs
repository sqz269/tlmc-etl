using Newtonsoft.Json;
using PushToDb.ExternalModel;
using Sharprompt;

namespace PushToDb.Operations;

public static class MpegDashPlaylistProcessor
{
    public static void PushMpegDashPlaylists(AppDbContext dbContext)
    {
        var filelistFp = Prompt.Input<string>("Enter path to hls-file-list.json", validators: [Validators.Required(), PathValidator.ValidateFilePath()]);

        Console.WriteLine("Loading HLS MPD Targets");
        var targets = JsonConvert.DeserializeObject<List<HlsDashCvtList>>(File.ReadAllText(filelistFp));
        if  (targets == null || targets.Count == 0)
        {
            Console.WriteLine("No HLS MPD Targets found in the file");
            return;
        }

        // Prepare objects
        var 
    }
}