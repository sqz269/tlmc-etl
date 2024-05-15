from io import TextIOWrapper
import json
import os
import subprocess
import typing
import mslex
import shlex


def append_file(fp: str, content: str, create_if_not_exist: bool = True):
    if create_if_not_exist:
        if not os.path.isfile(fp):
            with open(fp, "w") as f:
                pass

    with open(fp, "a", encoding="utf-8") as f:
        f.write(content)


def open_for_read(fp: str, create_if_not_exist: bool = True) -> TextIOWrapper:
    if create_if_not_exist:
        if not os.path.isfile(fp):
            with open(fp, "w") as f:
                pass

    file = open(fp, "r", encoding="utf-8")
    return file


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


def get_cuesheet_attr(path: str) -> str:
    probe_result = probe_flac("ffprobe", path)
    if probe_result is None:
        return None

    result = json.loads(probe_result)
    if "format" not in result:
        return None

    if "tags" not in result["format"]:
        return None

    tags = [i.lower() for i in result["format"]["tags"].keys()]
    if "cuesheet" in tags:
        return result["format"]["tags"]["cuesheet"]
    return None


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


class LSTAR:
    FILES = 0b01
    DIRECTORIES = 0b10
    ALL = 0b11


def ls(fp, target: int = LSTAR.ALL):
    results = []
    for o in os.listdir(fp):
        full = os.path.join(fp, o)
        if os.path.isfile(o) and target & LSTAR.FILES:
            results.append(full)
        if os.path.isdir(o) and target & LSTAR.DIRECTORIES:
            results.append(full)

    return results


def ls_d(fp: str, depth: int = 1, target: int = LSTAR.ALL):
    """
    List directories at a specified depth relative to the root (fp)

    For example, with depth = 1, it behave like a regular ls,
        Listing all files and directories imm relative to fp

    with depth = 2, it will list all files and directories
        of all the children of fp, essentially, it becomes ls(ls(fp))
    """

    queue = [fp]
    dir_result = []
    result = []
    for i in range(depth):
        for q in queue:
            for o in os.listdir(q):
                full = os.path.join(q, o)
                if os.path.isfile(full) and target & LSTAR.FILES:
                    result.append(full)
                if os.path.isdir(full):
                    dir_result.append(full)
                    if target & LSTAR.DIRECTORIES:
                        result.append(full)

        if i + 1 != depth:
            queue.clear()
            queue.extend(dir_result)
            dir_result.clear()
            result.clear()

    return result
