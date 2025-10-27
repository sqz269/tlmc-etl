using Newtonsoft.Json;

namespace PushToDb.ExternalModel;

public class HlsDashCvtList
{
    [JsonProperty("output_mpd")]
    public string OutputMpd { get; set; }
}