import json
import re
from typing import Dict, Optional
from urllib.parse import urlparse, quote_plus
import furl

import httpx
import mwparserfromhell as mw

from ExternalInfo.CacheInfoProvider.Cache import cached
from ExternalInfo.CacheInfoProvider.AdvancedCache import advanced_cache
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef

from Shared import utils
song_wiki_page_cache_path = utils.get_output_path(
    CachePathDef, CachePathDef.THWIKI_SONG_INFO_WIKI_PAGE_CACHE_DIR
)


def extract_title_from_url(url):
    parsed = furl.furl(url)
    return parsed.path.segments[-1]
    # return url.split("/")[-1]


def __extract_redirect_link(src) -> Optional[str]:
    redirect_keywords = ["#重定向", "#redirect"]
    is_redirect = False
    for keyword in redirect_keywords:
        if keyword in src.lower():
            is_redirect = True
            break
    
    if not is_redirect:
        return None


    parsed = mw.parse(src)
    redirect_link = parsed.filter_wikilinks()[0]
    return str(redirect_link.title)

def __get_wiki_page_content(api_response: Dict) -> Optional[str]:
    page = list(api_response["query"]["pages"].values())[0]
    if "missing" in page:
        return None
    
    try:
        page["revisions"][0]["*"]
    except KeyError:
        return None
    
    return page["revisions"][0]["*"]

def query_keywords(query, cache_id, cache_path) -> Optional[dict]:

    @advanced_cache(
        cache_id=cache_id,
        cache_dir=cache_path,
        debug=True,
        cache_save_transformer=json.dumps,
        cache_load_transformer=json.loads,
    )
    def __query_keywords(_query):
        HEADER = {
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://thwiki.cc/",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua-mobile": "?0",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
            "sec-ch-ua-platform": '"Windows"',
        }

        params = {
            "action": "opensearch",
            "format": "json",
            "formatversion": "2",
            "redirects": "display",
            "search": f"{_query}",
            "namespace": "0|4|12|102|108|506|508|512",
            "limit": "12",
        }

        response = httpx.get("https://thwiki.cc/api.php", params=params, headers=HEADER)
        search = json.loads(response.text)
        results = {
            "query": search[0],
            "results": {
                kw.lower(): (link, desc)
                for kw, link, desc in zip(search[1], search[3], search[2])
            },
        }
        return results

    return __query_keywords(query)

def get_thwiki_source_raw_resp(page_title, cache_id, cache_path) -> Optional[Dict]:
    @advanced_cache(
        cache_id=cache_id,
        cache_dir=cache_path,
        debug=True,
        cache_load_transformer=json.loads,
        cache_save_transformer=json.dumps,
    )
    def __get_thwiki_source(page_title):
        PAGE_SRC_URL = "https://thwiki.cc/api.php?action=query&prop=revisions&rvprop=content&format=json&titles={path}&utf8=1"
        HEADER = {
            "sec-ch-ua": '" Not A;Brand"lyrics_author;v="99", "Chromium";v="102", "Google Chrome";v="102"',
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://thwiki.cc/",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua-mobile": "?0",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
            "sec-ch-ua-platform": '"Windows"',
        }

        # URL encode the page title
        page_title_encoded = quote_plus(page_title)
        page_title = PAGE_SRC_URL.format(path=page_title_encoded)
        response = httpx.get(page_title, headers=HEADER)
        if response.status_code != 200:
            print(
                "Failed to get page source for {path}. Error: {code}".format(
                    path=page_title, code=response.status_code
                )
            )
            raise Exception(
                "Failed to get page source for {path}. Error: {code}".format(
                    path=page_title, code=response.status_code
                )
            )

        j = response.json()
        return j
    
    return __get_thwiki_source(page_title)


def get_thwiki_source_follow_redircts(page_title, cache_id, cache_path) -> Optional[Dict]:
    @advanced_cache(
        cache_id=cache_id,
        cache_dir=cache_path,
        cache_load_transformer=json.loads,
        cache_save_transformer=json.dumps,
    )
    def __get_thwiki_source_follow_redircts(page_title):
        redirect_check = re.compile(
            r"\#(?:(?:redirect)|(?:重定向)) ?\[\[(.+)\]\]", re.IGNORECASE
        )

        for _ in range(5):
            target_title = page_title
            page_src = get_thwiki_source_raw_resp(target_title, cache_id, cache_path)
            if not page_src:
                return None
            
            page_content = __get_wiki_page_content(page_src)
            redirect_target = __extract_redirect_link(page_content)
            if not redirect_target:
                return page_src
            
            page_title = redirect_target

        print(f"Failed to follow redirects for {page_title}. Max redirects reached.")
        return None

    return __get_thwiki_source_follow_redircts(page_title)


def get_thwiki_page_content_after_redirects(page_title, cache_id, cache_path) -> Optional[str]:
    page_src = get_thwiki_source_follow_redircts(page_title, cache_id, cache_path)
    if not page_src:
        return None
    
    return __get_wiki_page_content(page_src)
