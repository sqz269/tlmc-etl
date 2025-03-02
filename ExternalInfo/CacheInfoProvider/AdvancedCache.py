import datetime
import os
import re
from typing import Any, Callable, Optional

import hashlib
import ExternalInfo.ThwikiInfoProvider.Databases.path_definitions as DatabasesPathDef
from ExternalInfo.CacheInfoProvider.Model.AdvancedCacheModel import (
    AdvancedSourceCacheTable
)


def adv_cache_hashed_id_generator(*args):
    return hashlib.md5("".join([str(x) for x in args]).encode()).hexdigest()


def advanced_cache(
    cache_id,
    cache_dir,
    debug=False,
    # not using pickle cuz we might be caching stuff that is from the internet
    cache_save_transformer: Optional[Callable[[Any], str]] = lambda x: str(x),
    cache_load_transformer: Optional[Callable[[str], Any]] = lambda x: x,
    cache_filename_generator: Optional[Callable[[Any], str]] = lambda x: str(x),
):
    norm_path = lambda path, subchar="_": re.sub(r"\<|\>|\:|\"|\/|\\|\||\?|\*", subchar, path)

    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)

    def actual_decorator(func):

        def wrapper(*args, **kwargs):
            path_id = cache_id + "__" + "__".join([str(norm_path(x)) for x in args])
            if cache_filename_generator:
                path_id = cache_filename_generator(path_id)
            if (
                AdvancedSourceCacheTable.select()
                .where(AdvancedSourceCacheTable.path == path_id)
                .exists()
            ):
                cached = AdvancedSourceCacheTable.get(
                    AdvancedSourceCacheTable.path == path_id
                ).cached_source_path
                if cached != "" and os.path.exists(cached):
                    if debug:
                        print("Cache Hit for " + path_id)
                    with open(cached, "r", encoding="utf-8") as f:
                        return cache_load_transformer(f.read())
            if debug:
                print("Cache Miss for " + path_id)
            src = func(*args, **kwargs)
            with open(
                caced_src_path := os.path.join(cache_dir, path_id),
                "w",
                encoding="utf-8",
            ) as f:
                if debug:
                    print("Caching " + path_id)
                f.write(cache_save_transformer(src))
                if (
                    AdvancedSourceCacheTable.select()
                    .where(AdvancedSourceCacheTable.path == path_id)
                    .exists()
                ):
                    AdvancedSourceCacheTable.replace(
                        path=path_id,
                        cached_source_path=caced_src_path,
                        time_cached=datetime.datetime.now(),
                    )
                else:
                    AdvancedSourceCacheTable.create(
                        path=path_id,
                        cached_source_path=caced_src_path,
                        time_cached=datetime.datetime.now(),
                    )
            return src

        return wrapper

    return actual_decorator
