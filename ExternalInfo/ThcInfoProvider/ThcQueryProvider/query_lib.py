import httpx
import json
import unicodedata

def remove_non_content_letters(text):
    normalized = unicodedata.normalize('NFKD', text)
    for char in normalized:
        if not unicodedata.category(char).startswith('L'):
            normalized = normalized.replace(char, '')
    return normalized

def query_thc(album_name):
    HEADER = {
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://thwiki.cc/',
        'X-Requested-With': 'XMLHttpRequest',
        'sec-ch-ua-mobile': '?0',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
        'sec-ch-ua-platform': '"Windows"',
    }

    params = {
        'action': 'opensearch',
        'format': 'json',
        'formatversion': '2',
        'redirects': 'display',
        'search': f'{album_name}',
        'namespace': '0|4|12|102|108|506|508|512',
        'limit': '12',
    }

    response = httpx.get('https://thwiki.cc/api.php', params=params, headers=HEADER)
    search = json.loads(response.text)
    results = {
        "query": search[0],
        "results": {kw.lower(): (link, desc) for kw, link, desc in zip(search[1], search[3], search[2])}
    }
    return results