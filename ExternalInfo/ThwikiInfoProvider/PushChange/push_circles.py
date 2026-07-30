"""Pushes extended circle metadata (the thwiki artist pass) to the v6 backend.

Replaces commit_circle_extended_metadata.py: the v5 json-patch surface is
gone; v6 upserts by exact name via

  PUT api/internal/circle   [ {name, status, established, country, websites}, ... ]

Runs after the ThwikiArtistPageQueryScraper stages have populated
circles_info.db. Batched; safe to re-run.
"""

import json
import re

from ExternalInfo.ThwikiInfoProvider.PushChange.api_client import make_session, send
from ExternalInfo.ThwikiInfoProvider.ThwikiArtistPageQueryScraper.Model.CircleData import (
    CircleData,
    QueryStatus,
)

BATCH_SIZE = 200

country_map = {
    "日本": "jpn",
    "中国大陆": "chn",
    "美国": "usa",
    "俄罗斯": "rus",
    "德国": "deu",
    "印度尼西亚": "idn",
    "加拿大": "can",
    "台湾": "twn",
    "英国": "gbr",
    "韩国": "kor",
    "阿根廷": "arg",
    "瑞典": "swe",
    "香港": "hkg",
    "法国": "fra",
    "国际": "int",
    "澳大利亚": "aus",
    "芬兰": "fin",
    "波兰": "pol",
    "墨西哥": "mex",
    "匈牙利": "hun",
    "中国大陆，日本": "int",
    "土耳其": "tur",
    "捷克": "cze",
    "马来西亚": "mys",
    "拉丁美洲": "int",
    "越南": "vnm",
    "菲律宾": "phl",
    "荷兰": "nld",
    "波多黎各": "pri",
    "泰国": "tha",
    "乌克兰": "ukr",
}

# thwiki status -> wire CircleStatus (snake_case enum values)
status_map = {
    "活动": "active",
    "休止": "inactive",
    "解散": "disbanded",
    "转入非东方": "transfer",
    "未知": "unknown",
    "寒暑假活动": "active",
}

INVALID_MARK = re.compile(r"\{\{失效标记\}\}")
YEAR = re.compile(r"(\d{4})")


def to_dto(circle: CircleData):
    dto = {"name": circle.circle_name}

    if circle.circle_status is not None:
        dto["status"] = status_map[circle.circle_status]

    if circle.circle_est is not None:
        match = YEAR.search(circle.circle_est)
        if match:
            dto["established"] = f"{match.group(1)}-01-01"

    if circle.circle_country is not None:
        dto["country"] = country_map[circle.circle_country]

    websites = []
    raw = json.loads(circle.circle_web) if circle.circle_web else {}
    for entry in raw.values():
        url = entry.get("url")
        if not url:
            continue
        websites.append({
            "url": url,
            "invalid": INVALID_MARK.search(entry.get("desc", "")) is not None,
        })
    if websites:
        dto["websites"] = websites

    return dto


def main():
    dtos = [
        to_dto(circle)
        for circle in CircleData.select().where(
            CircleData.circle_query_status == QueryStatus.SCRAPE_OK
        )
    ]
    print(f"{len(dtos)} circles to upsert")

    session = make_session()
    created = updated = 0
    failures = []
    for i in range(0, len(dtos), BATCH_SIZE):
        batch = dtos[i : i + BATCH_SIZE]
        resp = send(session, "PUT", "/api/internal/circle", batch)
        if resp.status_code == 200:
            body = resp.json()
            created += body.get("created", 0)
            updated += body.get("updated", 0)
        else:
            failures.append(f"batch {i}: {resp.status_code} {resp.text[:200]}")
        print(f"[{min(i + BATCH_SIZE, len(dtos))}/{len(dtos)}] created {created}, updated {updated}", end="\r")

    print()
    print(f"Done: {created} created, {updated} updated, {len(failures)} failed batches.")
    if failures:
        with open("push_circles_failures.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print("See push_circles_failures.txt")


if __name__ == "__main__":
    main()
