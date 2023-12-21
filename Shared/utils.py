import json
import os
import subprocess
import typing
import mslex
import shlex

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
            
def max_common_prefix(array1: typing.List[str], array2: typing.List[str]) -> typing.List[typing.Tuple[str, str]]:
    array1.sort()
    array2.sort()
    result = []
    for i in range(len(array1)):
        if os.path.commonprefix([array1[i], array2[i]]) == array1[i]:
            result.append((array1[i], array2[i]))
    return result
