import re
import os
import json
import time
import traceback

import httpx
import mwparserfromhell as mw
from bs4 import BeautifulSoup
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode

from Processor.ExternalInfoCollector.CacheInfoProvider.Cache import cached
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcArtistInfoProvider.Model.CircleData import (
    CircleData,
    CircleStatus,
    QueryStatus,
)
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcQueryProvider import (
    thc_query_provider as QueryProvider,
)

QUERY_STR_PATH = (
    r"InfoProviders/ThcInfoProvider/ThcArtistInfoProvider/thc_artist_info.json"
)

PAGE_SRC_URL = "https://thwiki.cc/index.php?title={path}&action=edit&viewsource=1"

HEADER = {
    "sec-ch-ua": '" Not A;Brand"lyrics_author;v="99", "Chromium";v="102", "Google Chrome";v="102"',
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://thwiki.cc/",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
    "sec-ch-ua-platform": '"Windows"',
}


def get_title_from_url(url):
    # parsed = urlparse(url)
    # return parsed.path.split('/')[-1] + ("" if parsed.fragment == "" else "#" + parsed.fragment) + ("" if parsed.params == "" else parsed.params)
    r = url.replace("https://thwiki.cc/", "")
    return r


@cached(
    cache_id="thc",
    cache_dir="./InfoProviders/ThcInfoProvider/ThcSongInfoProvider/Cached",
    debug=True,
)
def get_source(url):
    redirect_check = re.compile(
        r"\#(?:(?:redirect)|(?:重定向)) ?\[\[(.+)\]\]", re.IGNORECASE
    )
    url = PAGE_SRC_URL.format(path=get_title_from_url(url).replace("&", "%26"))

    # Replace & with Hex Code
    response = httpx.get(url, headers=HEADER)
    if response.status_code != 200:
        print(
            "Failed to get page source for {path}. Error: {code}".format(
                path=url, code=response.status_code
            )
        )
        raise Exception(
            "Failed to get page source for {path}. Error: {code}".format(
                path=url, code=response.status_code
            )
        )

    bs = BeautifulSoup(response.text, "lxml")
    src = bs.find("textarea", {"id": "wpTextbox1"})
    parsed = mw.parse(src.text)

    # Handle Redirection
    if redirect_check.search(str(parsed)):
        redir_link = parsed.filter_wikilinks()[0].title
        print("[REDIR] Redirected to: " + redir_link.strip())
        return get_source("https://thwiki.cc/" + redir_link.strip())

    return parsed


def query():
    query_result = {}

    number_of_artists = BasicCircle.select().count()
    cur = 0
    artist: BasicCircle
    for artist in BasicCircle.select():
        cur += 1
        padded_name = artist.name.ljust(20)
        print(f"[{cur}/{number_of_artists}] Fetching artist: {padded_name}", end="\r")

        try:
            result = QueryProvider.query_thc(artist.name)
        except:
            print(f"\n\nFailed to query artist: {artist.name}\n\n")
            query_result[artist.name] = None
            continue

        query_result[artist.name] = result
        time.sleep(0.2)

    with open(QUERY_STR_PATH, "w", encoding="utf-8") as f:
        json.dump(query_result, f, ensure_ascii=False, indent=4)


def rerun_failed():
    with open(QUERY_STR_PATH, "r", encoding="utf-8") as f:
        query_result = json.load(f)

    failed = []
    for artist, result in query_result.items():
        if result is None:
            failed.append(artist)

    number_of_artists = len(failed)
    print(f"Found {number_of_artists} failed requests")
    for artist in failed:
        try:
            print(f"Querying artist: {artist}", end="\r")
            result = QueryProvider.query_thc(artist)
        except:
            print(f"\n\nFailed to query artist: {artist}\n\n")
            query_result[artist] = None
            continue

        query_result[artist] = result
        time.sleep(0.2)

    with open(QUERY_STR_PATH, "w", encoding="utf-8") as f:
        json.dump(query_result, f, ensure_ascii=False, indent=4)

    return query_result


def ld_query():
    with open(QUERY_STR_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def verf_query(query_data):
    keyword = "同人社团"
    verf_failed = []
    for artist, result in query_data.items():
        if result is None:
            continue

        if not result["results"]:
            continue

        for key, value in result["results"].items():
            url, desc = value
            if keyword not in desc:
                verf_failed.append(artist)
                break
            else:
                break

    print(f"Verification failed for {len(verf_failed)} artists")
    for artist in verf_failed:
        print(artist)

    return verf_failed


def gen_stats(query_data):
    found = 0
    not_found = 0
    failed = 0
    for artist, result in query_data.items():
        if result is None:
            failed += 1
        elif not result["results"]:
            not_found += 1
        else:
            found += 1

    print(f"Found: {found}, Not Found: {not_found}, Failed: {failed}")
    return found, not_found, failed


def get_artist_metadata(query_url):
    source = get_source(query_url)

    template = list(
        filter(lambda x: x.name.strip() == "同人社团信息", source.filter_templates())
    )

    if not template:
        return None

    metadata = {}

    key_params = {
        "社团名": "name",
        "成立时间": "founded",
        "当前状态": "status",
        "地区": "country",
    }

    web_link_prefix = "官网"
    web_link_desc_prefix = "官网说明"
    web_link_addi_prefix = "官网补充"

    web_links = {}

    for param in template[0].params:
        if not param.value.strip():
            continue

        if param.name.strip().startswith(web_link_desc_prefix):
            idx = param.name.strip().replace(web_link_desc_prefix, "")
            if idx:
                idx = int(idx)
            else:
                idx = 1

            if idx not in web_links:
                web_links[idx] = {}

            web_links[idx]["desc"] = param.value.strip()
            continue

        if param.name.strip().startswith(web_link_addi_prefix):
            idx = param.name.strip().replace(web_link_addi_prefix, "")
            if idx:
                idx = int(idx)
            else:
                idx = 1

            if idx not in web_links:
                web_links[idx] = {}

            web_links[idx]["addi"] = param.value.strip()
            continue

        if param.name.strip().startswith(web_link_prefix):
            idx = param.name.strip().replace(web_link_prefix, "")
            if idx:
                idx = int(idx)
            else:
                idx = 1

            if idx not in web_links:
                web_links[idx] = {}

            web_links[idx]["url"] = param.value.strip()
            continue

        if param.name.strip() in key_params:
            metadata[key_params[param.name.strip()]] = param.value.strip()
            continue

        print(param.name.strip(), param.value.strip())

    metadata["web_links"] = web_links

    return metadata


def push_initial_data():
    obj = []
    query_result = ld_query()
    gen_stats(query_result)

    invalid = verf_query(query_result)
    keyword = "同人社团"
    for idx, (artist, result) in enumerate(query_result.items()):
        print(f"Generating Data: {idx}/{len(query_result)}", end="\r")
        if not result:
            obj.append(
                {
                    "circle_name": artist,
                    "circle_scraped": False,
                    "circle_query_status": QueryStatus.FAILED,
                }
            )
            continue

        if not result["results"]:
            obj.append(
                {
                    "circle_name": artist,
                    "circle_scraped": False,
                    "circle_query_status": QueryStatus.NO_RESULT,
                }
            )
            continue

        if artist in invalid:
            obj.append(
                {
                    "circle_name": artist,
                    "circle_scraped": False,
                    "circle_query_status": QueryStatus.INVALID,
                }
            )
            continue

        for key, value in result["results"].items():
            url, desc = value
            if keyword not in desc:
                continue

            obj.append(
                {
                    "circle_name": artist,
                    "circle_scraped": False,
                    "circle_query_status": QueryStatus.SUCCESS,
                    "circle_query_url": url,
                }
            )
            break

    cd_obj = []
    for item in obj:
        cd_obj.append(CircleData(**item))
    print(f"Inserting {len(cd_obj)} objects")
    CircleData.bulk_create(cd_obj)


def scrape_artist(circle: CircleData):
    print(f"Retrieving artist: {str(circle.circle_name).ljust(20)}", end="\r")
    try:
        result = get_artist_metadata(circle.circle_query_url)
    except Exception as e:
        print(f"\n\nFailed to query artist: {circle.circle_name}\n\n")
        print("ERROR:")
        print(e)
        circle.circle_scraped = True
        circle.circle_query_status = QueryStatus.SCRAPE_FAILED
        circle.save()
        return

    if result is None:
        circle.circle_scraped = True
        circle.circle_query_status = QueryStatus.SCRAPE_FAILED
        circle.save()
        return

    circle.circle_scraped = True
    circle.circle_query_status = QueryStatus.SCRAPE_OK

    circle.circle_est = result.get("founded")
    circle.circle_status = result.get("status")
    circle.circle_country = result.get("country")
    circle.circle_web = json.dumps(result.get("web_links", {}), ensure_ascii=False)

    circle.save()
    time.sleep(0.2)


def get_artists_all():
    circle: CircleData
    for circle in CircleData.select().where(
        CircleData.circle_scraped == False
        and CircleData.circle_query_status == QueryStatus.SUCCESS
    ):
        scrape_artist(circle)


def retry_scrape_failed():
    circle: CircleData
    for circle in CircleData.select().where(
        CircleData.circle_query_status == QueryStatus.SCRAPE_FAILED
    ):
        scrape_artist(circle)


def main():
    if not os.path.exists(QUERY_STR_PATH):
        query()

    # Check if existing data in db
    if CircleData.select().count() == 0:
        rerun_failed()
        push_initial_data()

    # get_artists_all()
    retry_scrape_failed()


if __name__ == "__main__":
    main()
