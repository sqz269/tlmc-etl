from mwparserfromhell.wikicode import Wikicode

def number_of_nodes(code: Wikicode) -> int:
    return len(code.nodes)