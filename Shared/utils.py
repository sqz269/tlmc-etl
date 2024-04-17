import json
import os
import subprocess
import typing
import mslex
import shlex


def get_output_path(module, name):
    module_path = os.path.dirname(module.__file__)
    return os.path.join(module_path, name)


def get_self_output_path(module_fp, name):
    module_path = os.path.dirname(module_fp)
    return os.path.join(module_path, name)

def join_paths(*paths):
    """
    Join multiple paths using the separator detected from the first path argument.
    If no separator is detected, use os.sep as the separator.
    """
    sep = os.sep
    if len(paths) > 0:
        first_path = paths[0]
        if "/" in first_path:
            sep = "/"
        elif "\\" in first_path:
            sep = "\\"

    # strip all separators from the end of each path
    paths = [path.rstrip(sep) for path in paths]
    return sep.join(paths)


def get_file_relative(path, *args):
    """
    Returns the path of a file relative to the given path.

    Args:
        path (str): The absolute path of the file.
        *args (str): Additional path components to be joined with the relative path.

    Returns:
        str: The relative path of the file.

    """
    return os.path.join(os.path.dirname(path), *args)


def oslex_quote(path):
    if os.name == "nt":
        return mslex.quote(path)
    return shlex.quote(path)


def probe_flac(ffprobe: str, path: str):
    exec = ffprobe
    args = [
        "-show_format",
        "-of",
        "json",
        "-i",
        path,
        "-hide_banner",
        "-v",
        "quiet",
    ]
    cmd = [exec] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = p.communicate()
    if err:
        print(f"\n{err}\n")

        return None
    return out


def check_cuesheet_attr(path: str) -> bool:
    probe_result = probe_flac("ffprobe", path)
    if probe_result is None:
        return False

    result = json.loads(probe_result)
    if "format" not in result:
        return False

    if "tags" not in result["format"]:
        return False

    tags = [i.lower() for i in result["format"]["tags"].keys()]
    if "cuesheet" in tags:
        return True
    return False


def recurse_search(path: str, target: str):
    for root, dirs, files in os.walk(path):
        for file in files:
            if file == target:
                return os.path.join(root, file)


def max_common_prefix(
    array1: typing.List[str], array2: typing.List[str]
) -> typing.List[typing.Tuple[str, str]]:
    # Function to find the longest common prefix between two strings
    def longest_common_prefix(str1: str, str2: str) -> str:
        i = 0
        while i < len(str1) and i < len(str2) and str1[i] == str2[i]:
            i += 1
        return str1[:i]

    # Pairing items with the max common prefix
    result = []
    used_indices = set()  # To track used elements in array2
    for str1 in array1:
        max_prefix = ""
        max_prefix_pair = ("", "")
        for idx, str2 in enumerate(array2):
            # Skip if element is already used
            if idx in used_indices:
                continue
            # Find longest common prefix and update max_prefix if longer
            common_prefix = longest_common_prefix(str1, str2)
            if len(common_prefix) > len(max_prefix):
                max_prefix = common_prefix
                max_prefix_pair = (str1, str2)
                paired_idx = idx
        if max_prefix_pair != ("", ""):  # If a pair is formed
            result.append(max_prefix_pair)
            used_indices.add(paired_idx)  # Mark as used

    return result
