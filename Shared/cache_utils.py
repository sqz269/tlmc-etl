import os
import json


def check_cache(key, store_path):
    if not os.path.exists(store_path):
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(store_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    return key in cache


def store_cache(key, value, store_path):
    if not os.path.exists(store_path):
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    with open(store_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    cache[key] = value
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, sort_keys=True, ensure_ascii=False)


def delete_cache(key, store_path):
    with open(store_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    del cache[key]
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, sort_keys=True, ensure_ascii=False)


def load_cache(key, store_path, default=None):
    with open(store_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    return cache.get(key, default)
