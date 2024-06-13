using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using PushToDb.Model;
using Sharprompt;

namespace PushToDb.Operations;

public static class CircleMetadataProcessor
{
    public static void PushBasicCircleData(AppDbContext context)
    {
        var circleFp = Prompt.Input<string>("Enter path to artist_scanner.discovery.merged_artists.output.json", validators: [Validators.Required(), PathValidator.ValidateFilePath()]);

        // get json data from the file
        var circleJsonStr = File.ReadAllText(circleFp);
        var circleDataJson = JObject.Parse(circleJsonStr);

        var circlesObject = new List<Circle>();

        var knownIdsTracking = new HashSet<string>();
        // get the circle data
        foreach (var (circleRaw, circleData) in circleDataJson)
        {
            bool isNew = (bool)circleData!["new"]!;
            if (!isNew)
            {
                continue;
            }
            

            // Skip compound ids
            var knownIds = circleData["known_id"]!.ToObject<List<string>>();

            if (knownIds.Count > 1)
            {
                continue;
            }

            var aliases = circleData["alias"]!.ToObject<List<string>>();
            var name = circleData["name"]!.ToString();
            var id = knownIds.First();
            if (knownIdsTracking.Contains(id))
            {
                // Skip duplicate ids
                Console.WriteLine($"Skipping duplicate id, Known Id: {id}");
                continue;
            }

            knownIdsTracking.Add(id);

            Console.WriteLine($"Creating Circle Object {name}");
            var circle = new Circle
            {
                Id = Guid.Parse(id),
                Name = name,
                Status = CircleStatus.Unset,
                Alias = aliases
            };

            circlesObject.Add(circle);
        }

        // Bulk create the circles
        Console.WriteLine("Writing circle data into db");
        context.Circles.AddRange(circlesObject);
        context.SaveChanges();
        Console.WriteLine($"Push Complete, {circlesObject.Count} records inserted");
    }
}