from ExternalInfo.CacheInfoProvider.Cache import get_cache_id
from ExternalInfo.CacheInfoProvider.Model.CacheModel import (
    SourceCacheTable,
)

if __name__ == "__main__":
    print("Enter list of cache id in form of URL to purge:")

    cache_ids = []
    while True:
        cache_id = input()
        if cache_id == "":
            break
        cache_ids.append(cache_id)

    to_delete = []
    not_found = []
    for cache_id in cache_ids:
        path_id = get_cache_id(cache_id, "thc")
        if SourceCacheTable.select().where(SourceCacheTable.path == path_id).exists():
            to_delete.append(path_id)
        else:
            not_found.append(path_id)

    print("Found " + str(len(to_delete)) + " cache entries to delete.")
    print("Not Found " + str(len(not_found)))

    for path_id in not_found:
        print("Not Found " + path_id)

    print("Proceed? (y/n)")
    if input() == "y":
        for path_id in to_delete:
            SourceCacheTable.delete().where(SourceCacheTable.path == path_id).execute()
            print("Purged " + path_id)

        # if (SourceCacheTable.select().where(SourceCacheTable.path == path_id).exists()):
        #     SourceCacheTable.delete().where(SourceCacheTable.path == path_id).execute()
        #     print("Purged " + cache_id)
