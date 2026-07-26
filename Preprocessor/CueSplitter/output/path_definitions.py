CUE_SCANNER_OUTPUT_NAME = "scanner.potential.output.json"
CUE_DESIGNATER_OUTPUT_NAME = "designator.designated.output.json"
CUE_DESIGNATER_USER_PAIR_CACHE_NAME = "designator.user_pair_cache.output.json"

# Verdict per album from the cue analysis. The scanner flags anything that merely
# looks suspicious, including ~1300 albums that are already split; designating
# those would build profiles from stale CUESHEET tags and the splitter would then
# delete audio that never needed touching. The designator filters on this.
CUE_SPLIT_PLAN_OUTPUT_NAME = "cue_split_plan.json"
