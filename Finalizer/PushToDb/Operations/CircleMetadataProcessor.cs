using Newtonsoft.Json.Linq;
using PushToDb.Model;
using Sharprompt;

namespace PushToDb.Operations;

public static class CircleMetadataProcessor
{
    public static void PushBasicCircleData(AppDbContext context, string? circleFilePath = null)
    {
        var circleFp = circleFilePath
            ?? Prompt.Input<string>("Enter path to artist_scanner.discovery.merged_artists.output.json", validators: [Validators.Required(), PathValidator.ValidateFilePath()]);

        // get json data from the file
        var circleJsonStr = File.ReadAllText(circleFp);
        var circleDataJson = JObject.Parse(circleJsonStr);

        var circlesObject = new List<Circle>();

        var knownIdsTracking = new HashSet<string>();
        // Compound entries (collaborations) don't get a circle row of their own —
        // their known_id list names the constituent circles, and release
        // attribution lands on those via release_circle. What they DO need is for
        // every constituent to exist, so that attribution can't silently vanish
        // the way it did when the old loader skipped them wholesale.
        var compoundConstituents = new Dictionary<string, List<string>>();

        foreach (var (circleRaw, circleData) in circleDataJson)
        {
            bool isNew = (bool)circleData!["new"]!;
            var knownIds = circleData["known_id"]!.ToObject<List<string>>()!;

            if (knownIds.Count > 1)
            {
                compoundConstituents[circleRaw] = knownIds;
                continue;
            }

            if (!isNew)
            {
                continue;
            }

            var aliases = circleData["alias"]!.ToObject<List<string>>()!;
            var name = circleData["name"]!.ToString();
            var id = knownIds.First();
            if (knownIdsTracking.Contains(id))
            {
                // Skip duplicate ids
                Console.WriteLine($"Skipping duplicate id, Known Id: {id}");
                continue;
            }

            knownIdsTracking.Add(id);

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

        // Verify collaboration constituents resolve to a circle row (inserted this
        // run or already present), so release attribution has somewhere to land.
        var allIds = context.Circles.Select(c => c.Id.ToString()).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var broken = compoundConstituents
            .Select(kv => (Raw: kv.Key, Missing: kv.Value.Where(id => !allIds.Contains(id)).ToList()))
            .Where(x => x.Missing.Count > 0)
            .ToList();

        Console.WriteLine($"{compoundConstituents.Count} collaboration entries checked");
        if (broken.Count > 0)
        {
            Console.WriteLine($"WARNING: {broken.Count} collaboration(s) reference circles with no row; " +
                              "their releases will lose that attribution:");
            foreach (var (raw, missing) in broken.Take(20))
            {
                Console.WriteLine($"  {raw}: missing {string.Join(", ", missing)}");
            }
        }
    }
}
