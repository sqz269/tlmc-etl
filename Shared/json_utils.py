import json


def json_dump(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def json_load(path):
    with open(path, "w", encoding="utf-8") as f:
        return json.load(f)
