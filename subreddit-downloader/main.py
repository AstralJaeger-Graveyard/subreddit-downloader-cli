import asyncio
import math
import os
import os.path
import platform
import sys
import time
import traceback
from datetime import datetime, timedelta
from glob import glob
from urllib.parse import urlparse

import asyncpraw
from colorama import init
from requests import HTTPError

from downloaders import *
from urlresolvers import StandardUrlResolver
from environment import ensure_environment
from environmentlabels import *

# Constants
VERSION = "0.2.0"
HEADERS = 96
LIMIT = 1000
EARLY_ABORT = 3 * math.ceil(math.log10(LIMIT))   # Early abort for refresh-mode

# Important environment
generic_downloader = GenericDownloader()
used_downloaders = [
    generic_downloader,
    RedditDownloader(),
    RedgifsDownloader(),
    ImgurDownloader()
]

env = ensure_environment(used_downloaders)
temp_dir = env[TEMP_LOCATION]
os.makedirs(temp_dir, exist_ok=True)
data_dir = env[DATA_LOCATION]
os.makedirs(data_dir, exist_ok=True)
downloader_registry: dict[Pattern, BaseDownloader] = {}

# Initialize downloaders with environment
for downloader in used_downloaders:
    downloader.init(env)
    print(f"> {Fore.BLUE}{downloader.__class__.__name__}{Fore.RESET} supports {len(downloader.get_supported_domains())} providers")
    for host_pattern in downloader.get_supported_domains():
        downloader_registry[host_pattern] = downloader

stats: dict[str, int] = {}


def acoustic_alert():
    if platform.system() == 'Windows':
        import winsound
        duration = 1000  # milliseconds
        freq = 440  # Hz
        winsound.Beep(freq, duration)


async def download(url: str, target: str) -> str:

    result = urlparse(url)
    urlpath = None
    if urlpath and not result.path == "":
        urlpath = result.path.split("/")[0]
    match_str = f"{result.hostname}/{urlpath}" if urlpath else result.hostname

    # Count used hosts
    if match_str in stats.keys():
        stats[match_str] = stats[match_str] + 1
    else:
        stats[match_str] = 1

    for provider in downloader_registry.keys():
        if re.match(provider, match_str):
            try:
                return await downloader_registry[provider].download(url, target)
            except HTTPError as httperror:
                return f"{Fore.RED}{httperror.__class__.__name__} {httperror} for {result.hostname}{Fore.RESET}"
            except Exception as error:
                acoustic_alert()
                print(f"{' ' * 18} {error}")
                traceback.print_exception(error)
                return f"{Fore.RED}{error.__class__.__name__} {error.code if hasattr(error, 'code') else '-'} for {result.hostname}{Fore.RESET}"

    return f"{Fore.YELLOW}No downloader for \'{match_str}\'{Fore.RESET}"


async def cleanup(data_dir: str, temp_dir) -> None:
    print(f"> {Fore.BLUE}Cleaning up folder{Fore.RESET}  : {data_dir}")
    print(f"> {Fore.BLUE}Temp. folder{Fore.RESET} : {temp_dir}")
    print("=" * HEADERS)
    dup_map: dict[int, str] = dict()
    for path, subdirs, files in os.walk(data_dir):
        for name in files:
            name_path = os.path.join(path, name)
            hex_key = int(name.split(".")[0], 16)
            if hex_key in dup_map:
                print(f" - Found duplicate file: {Fore.YELLOW}{name_path}{Fore.RESET} - {Fore.YELLOW}{dup_map[hex_key]}{Fore.RESET}")
                if name_path[0:name_path.rfind("/")] == dup_map[hex_key]:
                    os.unlink(name_path)
            else:
                dup_map[hex_key] = name_path
            if ".." in name:
                print(f" - Renaming malformed file: {Fore.YELLOW}{name}{Fore.RESET} - {Fore.YELLOW}{name.replace('..', '.')}{Fore.RESET}")
                os.rename(os.path.join(path, name), os.path.join(path, name.replace("..", ".")))
    print(f"Dupmap contained {len(dup_map)} elements")


async def main(args: list[str]):

    print("=" * HEADERS)
    print(f"{Fore.MAGENTA}Subreddit CLI Downloader{Fore.RESET} V{VERSION}".center(HEADERS))
    print(f"Application startup successful, environment loaded".center(HEADERS))
    print("=" * HEADERS)
    print("")

    reddit = asyncpraw.Reddit(
        client_id=env[REDDIT_CLIENT_ID],
        client_secret=env[REDDIT_CLIENT_SECRET],
        username=env[REDDIT_USER],
        password=env[REDDIT_PASSWORD],
        user_agent=f"{platform.system().lower()}:sr-downloader-cli:{VERSION} (by u/97hilfel)"
    )

    # Add check if no subreddit name is given
    subreddit_names = args[1:]
    refresh_mode = False

    if len(subreddit_names) == 0:
        print(f"No subreddit names passed, looking for existing resources and refreshing existing resources")
        existing = glob(os.path.join(data_dir, "ws-*"))
        subreddit_names = [srn.split(os.sep)[-1].replace("ws-", "") for srn in existing]
        refresh_mode = True

    if len(subreddit_names) > 1:
        print(f"Downloading multiple: {os.linesep}    - {Fore.RED}{f'{os.linesep}{Fore.RESET}    - {Fore.RED}'.join(sorted(subreddit_names))}{Fore.RESET}")

    for major, subreddit_name in enumerate(sorted(subreddit_names), 1):
        duplicate_count = 0
        subreddit = await reddit.subreddit(subreddit_name)
        target_dir = os.path.join(data_dir, f"ws-{subreddit.display_name.lower()}")
        os.makedirs(target_dir, exist_ok=True)

        print("=" * HEADERS)
        print(f"> {Fore.BLUE}Data folder{Fore.RESET}  : {data_dir}")
        print(f"> {Fore.BLUE}Temp. folder{Fore.RESET} : {temp_dir}")
        print(f"> {Fore.BLUE}Target folder{Fore.RESET}: {target_dir}")
        print(f"> {Fore.BLUE}Subreddit{Fore.RESET}    : r/{Fore.RED}{subreddit.display_name}{Fore.RESET}")
        print(f"> {Fore.BLUE}Limit{Fore.RESET}: {LIMIT}")
        if refresh_mode:
            print(f"> {Fore.BLUE}Early abort limit{Fore.RESET}: {EARLY_ABORT}")
        print("=" * HEADERS + "\n")

        idx: int = 0
        async for submission in subreddit.new(limit=LIMIT):
            await submission.load()
            score_color = Fore.GREEN if submission.score > 0 else Fore.RED
            created = datetime.fromtimestamp(submission.created_utc)

            urls = StandardUrlResolver().resolve(submission)

            idx += 1
            for url in urls:
                hex_digest = await download(url, target_dir)

                if hex_digest is None:
                    hex_digest = f"{Fore.RED}HEX DIGEST IS NONE{Fore.RESET}"

                if len(urls) > 1:
                    hex_digest = f"{Fore.BLUE}GALLERY{Fore.RESET} {hex_digest}"

                if "duplicate" in hex_digest.lower():
                    duplicate_count = duplicate_count + 1

                if not refresh_mode:
                    print(f" - {Fore.BLUE}{idx:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] <{created}> {submission.title} [{hex_digest}]")
                else:
                    print(f" - {Fore.BLUE}{major:3}{Fore.RESET}.{Fore.BLUE}{idx:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] <{created}> {submission.title} [{hex_digest}]")

                if "no downloader" in hex_digest.lower():
                    print(f"{' ' * 18} URL: {submission.url}")
                if refresh_mode and duplicate_count > EARLY_ABORT:
                    break

    await reddit.close()

    print("=" * HEADERS)
    total_calls = sum(stats.values())
    print(f"Used providers and cdn's over {total_calls} attempted downloads:")

    for key, value in reversed(sorted(stats.items(), key=lambda item: item[1])):
        color = Fore.GREEN if any(pattern.match(key) for pattern in downloader_registry.keys()) else Fore.RED
        print(f" - {Fore.BLUE}{key:>32}{Fore.RESET}: {value:4}  <{color}{round(value / total_calls * 10_000) / 100:4.1f}%{Fore.RESET}>")
    print("=" * HEADERS)
    await cleanup(data_dir, temp_dir)
    acoustic_alert()


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        init()
        asyncio.run(main(sys.argv))
    except KeyboardInterrupt:
        print(f"{Fore.RED}Stopped by keyboard interrupt{Fore.RESET}")
    except Exception as excep:
        print(f"{Fore.RED}Stopped by {excep.__class__.__name__}{Fore.RESET}")
        print(excep)

    for downloader in downloader_registry.values():
        downloader.close()

    elapsed = time.perf_counter() - start
    print(f"{Fore.BLUE}{__file__}{Fore.RESET} executed in {Fore.BLUE}{timedelta(seconds=elapsed)}{Fore.RESET} seconds.")
