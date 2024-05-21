import json
import re

import httpx
from ExternalInfo.ThwikiInfoProvider.ThwikiArtistInfoProvider.Model.CircleData import (
    CircleData,
)

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
}

status_map = {
    "活动": "Active",
    "休止": "Inactive",
    "解散": "Disbanded",
    "转入非东方": "Transfer",
    "未知": "Unknown",
    "寒暑假活动": "Active",
}


def mk_json_patch(data: CircleData) -> str:
    website = json.loads(data.circle_web) if (data.circle_web is not None) else {}
    patch = []

    isInvalidRegex = re.compile(r"\{\{失效标记\}\}")
    yearExtRegex = re.compile(r"(\d{4})")

    for key, value in website.items():
        # if a website only have desc, then ignore
        if value.get("url") is None:
            continue

        isInvalid = isInvalidRegex.search(value.get("desc", "")) is not None

    #     patch.append({
    #         "op": "add",
    #         "path": f"/Website/-",
    #         "value": {
    #             "Url": value["url"],
    #             "Invalid": isInvalid,
    #         }
    #     })

    # if (data.circle_est is not None):
    #     yearStr = f"{yearExtRegex.search(data.circle_est).group(1)}-01-01T00:00:00Z"
    #     patch.append({
    #         "op": "replace",
    #         "path": "/Established",
    #         "value": yearStr
    #     })

    # if (data.circle_country is not None):
    #     patch.append({
    #         "op": "replace",
    #         "path": "/Country",
    #         "value": country_map[data.circle_country]
    #     })

    # if (data.circle_status is not None):
    #     patch.append({
    #         "op": "replace",
    #         "path": "/Status",
    #         "value": status_map[data.circle_status]
    #     })

    if data.circle_query_url is not None:
        patch.append(
            {"op": "add", "path": "/DataSource/-", "value": data.circle_query_url}
        )

    return json.dumps(patch)


def send_request(patch: str, circle_id: int):
    url = f"http://localhost:5217/api/internal/circle/{circle_id}"
    headers = {"Content-Type": "application/json-patch+json"}
    response = httpx.patch(url, data=patch, headers=headers, verify=False)

    if response.status_code != 200:
        raise Exception(f"Response: {response.status_code} {response.text}")

    print(f"Patched {circle_id} successfully")


def reformat_special_char(s: str) -> str:
    special = ["/", "\\", "?", ",", "%", "#"]

    for c in special:
        s = s.replace(c, "_")

    return s


def get_id_from_name(name: str) -> int:
    url = f"http://localhost:5217/api/entity/circle/{reformat_special_char(name)}"
    response = httpx.get(url, verify=False)

    if response.status_code != 200:
        raise Exception(f"Response: {response.status_code} {response.text}")

    return response.json()["id"]


def main():
    id_map = {}
    circle: CircleData
    num = CircleData.select().count()
    i = 0
    for circle in CircleData.select():
        i += 1
        circle_id = get_id_from_name(circle.circle_name)
        id_map[circle.circle_name] = circle_id
        print(f"{i}/{num} Mapped {circle.circle_name} -> {circle_id}")

    input("Press enter to continue...")

    patches = {}

    for circle in CircleData.select():
        print(f"Processing {circle.circle_name}")
        patch = mk_json_patch(circle)
        patches[circle.circle_name] = patch

    input("Press enter to continue...")

    for name, patch in patches.items():
        try:
            send_request(patch, id_map[name])
        except Exception as e:
            print(f"Failed to patch {name}: {e}")
            input("Press enter to continue...")


if __name__ == "__main__":
    main()
