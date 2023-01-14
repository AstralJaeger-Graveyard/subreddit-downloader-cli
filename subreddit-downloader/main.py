import argparse
import asyncio
import datetime
import math
import os
import os.path
import platform
import re
import time
import urllib.parse
from datetime import timedelta
from glob import glob
from pathlib import Path

import requests
import asyncpraw
import ubelt
import xxhash
from asyncpraw import Reddit
from asyncpraw.models import Submission
from colorama import init, Fore

import environmentlabels as envlbl
from downloaders import BaseDownloader, GenericDownloader, RedditDownloader, RedgifsDownloader, ImgurDownloader, \
    NoDownloaderException
from environment import ensure_environment
from urlresolvers import StandardUrlResolver
from utils import is_sha256, load_dupmap, store_dupmap

# Constants
VERSION = "0.3.0"
HEADERS = 96
LIMIT = 1000
EARLY_ABORT = max(2 * math.ceil(math.log10(LIMIT)), 1)  # Early abort for refresh-mode

# CLI Constants
refresh_mode: bool = False
no_op: bool = False

generic_downloader = GenericDownloader()

# Register downloaders
used_downloaders = [
    generic_downloader,
    RedditDownloader(),
    RedgifsDownloader(),
    ImgurDownloader()
]

# Important environment
env = ensure_environment(used_downloaders)
downloader_registry: dict[re.Pattern, BaseDownloader] = {}

stats: dict[str, int] = {}
dup_map: dict[str, str] = dict()


async def download(url: str, target: str) -> (str, Path):
    """
        Download a file from an url choosing the correct downloader for the domain
        Params:
            url (str): The url to the file
            target (str): The Path to the target directory (must be created beforehand)
        Returns
            filename (str): the hash of the file
            filepath (Path): The Path to the file
    """
    result = urllib.parse.urlparse(url)
    urlpath = None
    if urlpath and result.path != "":
        urlpath = result.path.split("/")[0]
    match_str = f"{result.hostname}/{urlpath}" if urlpath else result.hostname

    # Count used hosts
    if match_str in stats.keys():
        stats[match_str] = stats[match_str] + 1
    else:
        stats[match_str] = 1

    for provider in downloader_registry.keys():
        if re.match(provider, match_str):
            return await downloader_registry[provider].download(url, target)

    raise NoDownloaderException


async def handle_text(submission: Submission, target_dir: str, job_id: int) -> None:

    submission_id = submission.id
    score_color = Fore.GREEN if submission.score > 0 else Fore.RED
    title = submission.title
    text = submission.selftext
    author = submission.author
    created = datetime.datetime.fromtimestamp(submission.created_utc)
    subreddit = submission.subreddit.display_name

    sanitized_title = title.lower()\
        .replace(' ', '_')\
        .replace('-', '_')
    sanitized_title = re.sub(r'\W+', '', sanitized_title)

    filename = f"{submission_id}_{sanitized_title}.md"

    filepath = Path(target_dir, filename)
    if filepath.exists():
        print(f" - {Fore.BLUE}{job_id:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
              f"{submission.title}")
        return
    else:
        with open(filepath, "w") as file:
            file.write(f"# {title}{os.linesep}")
            file.write(f"---{os.linesep}")
            file.write(f"Author: {author}{os.linesep}")
            file.write(f"Created: {created}{os.linesep}")
            file.write(f"Subreddit: {subreddit}{os.linesep}")
            file.write(f"---{os.linesep}")
            file.write(f"{text}")

    print(f" - {Fore.BLUE}{job_id:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
          f"{submission.title} [{filename}]")
    dup_map.update({submission.id: str(filepath)})


async def handle_url(url: str, submission: Submission, target_dir: str, jobid: int) -> None:
    score_color = Fore.GREEN if submission.score > 0 else Fore.RED
    try:
        digest, filepath = await download(url, target_dir)
        if digest == "":
            print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
                  f"{submission.title}")
        else:
            print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
                  f"{submission.title} [{digest}]")
        # Only add submission if download was successful
        dup_map.update({submission.id: str(filepath) if filepath is not None else ""})
    except NoDownloaderException:
        print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
              f"No downloader for url: {Fore.YELLOW}{url}{Fore.RESET}")
    except requests.exceptions.HTTPError as http_error:
        print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
              f"HTTP Error {Fore.YELLOW}{http_error}{Fore.RESET} for url: {Fore.YELLOW}{url}{Fore.RESET}")
        if hasattr(http_error.response, "status_code") and http_error.response.status_code == 404:
            dup_map.update({submission.id: ""})  # Data was probably deleted, no need to revisit
    except Exception as error:
        print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
              f"Error {Fore.YELLOW}{error}{Fore.RESET} for url: {Fore.YELLOW}{url}{Fore.RESET}")


async def handle_submission(submission: Submission, target_dir: str, jobid: int) -> None:
    try:
        if submission.is_self:
            await handle_text(submission, target_dir, jobid)
        else:
            urls = StandardUrlResolver().resolve(submission)
            for url in urls:
                await handle_url(url, submission, target_dir, jobid)
    except Exception as error:
        print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. Critical Error {Fore.RED}{error}{Fore.RESET} for submission: " +
              f"{Fore.RED}{submission.permalink}{Fore.RESET}")


async def handle_subreddit(reddit: Reddit, subreddit_name: str, data_dir: Path, meta_dir: Path) -> None:
    start_time = time.perf_counter()
    subreddit = await reddit.subreddit(subreddit_name)
    await subreddit.load()
    target_dir = os.path.join(data_dir, f"ws-{subreddit.display_name.lower()}")
    os.makedirs(target_dir, exist_ok=True)

    print("=" * HEADERS)
    print(f"> {Fore.BLUE}Subreddit{Fore.RESET}    : r/{Fore.RED}{subreddit.display_name}{Fore.RESET}")
    print(f"> {Fore.BLUE}Target folder{Fore.RESET}: {target_dir}")
    print("=" * HEADERS + os.linesep)

    async with asyncio.TaskGroup() as tg:

        max_retries = 3
        retries: int = 1  # How often it should be retried to download

        while retries < max_retries:
            jobid: int = 1  # Actual jobs that get downloaded
            taskid: int = 1  # Jobs that get checked but have already been downloaded
            try:
                async for submission in subreddit.new(limit=LIMIT):
                    if submission.id not in dup_map.keys():
                        await submission.load()
                        tg.create_task(handle_submission(submission, target_dir, jobid))
                        jobid += 1
                        if jobid > 10 and jobid % 50 == 0:
                            tg.create_task(store_dupmap(dup_map, meta_dir))
                    if (taskid % int(LIMIT / 50)) == 0:
                        print(" " * 3 +
                              f"{Fore.CYAN}Progress: approximately {round((taskid / LIMIT) * 100):2}% done " +
                              f" took {timedelta(seconds=(time.perf_counter() - start_time))} so far{Fore.RESET}")
                    taskid += 1
                retries = max_retries + 1
            except Exception as error:
                retries += 1
                print(f"An {Fore.RED}{error.__class__.__name__}{Fore.RESET} occurred: {error} retrieving " +
                      f"{max_retries - retries} more times")

    end_time = time.perf_counter()
    await store_dupmap(dup_map, meta_dir)
    print(f"> Downloading subreddit took {Fore.BLUE}{timedelta(seconds=(end_time - start_time))}{Fore.RESET} " +
          f"Duplicate map contains {Fore.BLUE}{len(dup_map)}{Fore.RESET} elements.")


async def cleanup(data_dir: Path, temp_dir: Path) -> None:
    # TODO: Cleanup the cleanup method, this feature is due to be removed or re-implemented
    print(f"> {Fore.BLUE}Cleaning up folder{Fore.RESET}  : {data_dir}")
    print(f"> {Fore.BLUE}Temp. folder{Fore.RESET} : {temp_dir}")
    print("=" * HEADERS)

    file_map: dict[int, str] = dict()

    for dir_path, dir_names, filenames in os.walk(data_dir):
        for name in filenames:
            try:
                name_path = os.path.join(dir_path, name)
                filepath = Path(dir_path) / name

                # Recalculate hash to use xxhash3
                if is_sha256(name) and False:
                    new_hash = ubelt.hash_file(Path(name_path), hasher=xxhash.xxh128)
                    new_path = Path(dir_path) / f"xx{new_hash}.{filepath.suffix}"
                    if new_path.exists():
                        # delete if the file is a duplicate
                        os.unlink(filepath)
                    else:
                        os.rename(name_path, new_path)

                if name.startswith(".") or filepath.suffix == ".xsl":
                    os.unlink(name_path)
                elif is_sha256(name):
                    try:
                        hex_key = int(name.split(".")[0], 16)
                        if hex_key in file_map:
                            if name_path[0:name_path.rfind("/")] == file_map[hex_key]:
                                print(f" - Found duplicate file: {Fore.YELLOW}{name_path}{Fore.RESET} - " +
                                      f"{Fore.YELLOW}{file_map[hex_key]}{Fore.RESET}")
                                os.unlink(name_path)
                        else:
                            file_map[hex_key] = name_path
                        if ".." in name:
                            print(f" - Renaming malformed file: {Fore.YELLOW}{name}{Fore.RESET} - " +
                                  f"{Fore.YELLOW}{name.replace('..', '.')}{Fore.RESET}")
                            os.rename(os.path.join(dir_path, name), os.path.join(dir_path, name.replace("..", ".")))
                    except ValueError:
                        pass
            except FileNotFoundError:
                pass
    print(f"Duplicate map contained {len(file_map)} elements")


def print_reporting(reporting_stats: dict[str, int]) -> None:
    """
        Prints a reporting to STDOUT
        Params:
            stats (Counter): The counter object to print
    """
    print("=" * HEADERS)
    total_calls = sum(reporting_stats.values())
    print(f"Used providers and cdn's over {total_calls} attempted downloads:")

    for key, value in reversed(sorted(reporting_stats.items(), key=lambda item: item[1])):
        color = Fore.RED
        if any(p.match(key) if p.match(key) is not None else False for p in downloader_registry.keys()):
            color = Fore.GREEN
        val_str = f"{value: 4}" if value is not None else "NONE"
        print(f" - {Fore.BLUE}{key:>48}{Fore.RESET}: {val_str}  " +
              f"<{color}{round(value / total_calls * 10_000) / 100:4.1f}%{Fore.RESET}>")
    print("=" * HEADERS)


def parse_args() -> argparse.Namespace:
    """ Parses CLI args
        Returns:
            namespace (argparse.Namespace): The parsed namespace
    """
    parser = argparse.ArgumentParser(description=f"A Subreddit Downloader V{VERSION} for the CLI", epilog="")
    parser.add_argument("subreddits", metavar="SR", nargs="*", help="The subreddit(s) to be downloaded")
    parser.add_argument("--data", "-d", required=True, action="store")
    parser.add_argument("--temp", "-t", required=False, action="store")
    parser.add_argument("--meta", "-m", required=False, action="store")
    parser.add_argument("--limit", "-l", required=False, action="store")
    parser.add_argument("--refresh", "-r", required=False, action="store_true")
    parser.add_argument("--no-cleanup", "-nc", required=False, action="store_true")
    parser.add_argument("--no-op", "-no", required=False, action="store_true")
    return parser.parse_args()


async def main() -> None:
    print("=" * HEADERS)
    print(f"{Fore.MAGENTA}Subreddit CLI Downloader{Fore.RESET} V{VERSION}".center(HEADERS))
    print(f"Application startup successful, environment loaded".center(HEADERS))
    print("=" * HEADERS)
    print("")

    # Initialize argparse
    global refresh_mode, no_op, dup_map, LIMIT

    p_args = parse_args()
    data_dir = Path(p_args.data)
    if not p_args.temp:
        temp_dir = Path(data_dir, "temp")
    else:
        temp_dir = p_args.temp

    if not p_args.meta:
        meta_dir = Path(data_dir, "meta")
    else:
        meta_dir = p_args.meta

    if p_args.limit:
        try:
            LIMIT = int(p_args.limit)
        except ValueError:
            pass

    refresh_mode = p_args.refresh
    no_cleanup = p_args.no_cleanup
    no_op = p_args.no_op
    subreddits = p_args.subreddits

    env[envlbl.DATA_LOCATION] = str(data_dir)
    env[envlbl.TEMP_LOCATION] = str(temp_dir)
    env[envlbl.META_LOCATION] = str(meta_dir)

    if not data_dir.exists():
        os.makedirs(data_dir, exist_ok=True)
    if not temp_dir.exists():
        os.makedirs(temp_dir, exist_ok=True)
    if not meta_dir.exists():
        os.makedirs(meta_dir, exist_ok=True)

    # Initialize downloaders with environment
    global downloader_registry
    for dl in used_downloaders:
        dl.init(env, no_op)
        print(
            f"> {Fore.BLUE}{dl.__class__.__name__}{Fore.RESET} supports {len(dl.get_supported_domains())} providers")
        for host_pattern in dl.get_supported_domains():
            downloader_registry[host_pattern] = dl

    # Load duplicate map
    dup_map = await load_dupmap(meta_dir)

    print("")
    print(f"> {Fore.BLUE}Duplicate map length{Fore.RESET}: {len(dup_map)}")
    print(f"> {Fore.BLUE}Data folder{Fore.RESET}  : {data_dir}")
    print(f"> {Fore.BLUE}Temp. folder{Fore.RESET} : {temp_dir}")
    print(f"> {Fore.BLUE}Meta. folder{Fore.RESET} : {meta_dir}")
    print(f"> {Fore.BLUE}Limit{Fore.RESET}        : {LIMIT}")

    if env[envlbl.REDDIT_USERNAME] and env[envlbl.REDDIT_PASSWORD]:
        reddit = asyncpraw.Reddit(
            client_id=env[envlbl.REDDIT_CLIENT_ID],
            client_secret=env[envlbl.REDDIT_CLIENT_SECRET],
            username=env[envlbl.REDDIT_USERNAME],
            password=env[envlbl.REDDIT_PASSWORD],
            user_agent=f"{platform.system().lower()}:sr-downloader-cli:{VERSION} (by u/97hilfel)"
        )
    else:
        reddit = asyncpraw.Reddit(
            client_id=env[envlbl.REDDIT_CLIENT_ID],
            client_secret=env[envlbl.REDDIT_CLIENT_SECRET],
            user_agent=f"{platform.system().lower()}:sr-downloader-cli:{VERSION} (by u/97hilfel)"
        )

    # Add check if no subreddit name is given
    subreddit_names = list(subreddits)

    if refresh_mode or len(subreddit_names) == 0:
        print(f"No subreddit names passed, looking for existing resources and refreshing existing resources")
        existing = glob(os.path.join(data_dir, "ws-*"))
        subreddit_names = subreddit_names + sorted([srn.split(os.sep)[-1].replace("ws-", "") for srn in existing])

    if len(subreddit_names) > 1:
        print(f"Downloading multiple: {os.linesep}" +
              f"    - {Fore.RED}{f'{os.linesep}{Fore.RESET}    - {Fore.RED}'.join(subreddit_names)}" +
              f"{Fore.RESET}")

    for idx, subreddit_name in enumerate(subreddit_names):
        print(f"> r/{Fore.LIGHTBLUE_EX}{subreddit_names[idx - 1] if idx > 0 else 'FIRST'}{Fore.RESET} >> " +
              f"r/{Fore.CYAN}{subreddit_name}{Fore.RESET} >> " +
              f"r/{Fore.BLUE}{subreddit_names[idx + 1] if idx + 1 < len(subreddit_names) else 'LAST'}{Fore.RESET}")
        print(f"> {Fore.CYAN}{round((1 - (idx + 1) / len(subreddit_names)) * 100)}{Fore.RESET}% remaining")
        await handle_subreddit(reddit, subreddit_name, data_dir, meta_dir)

    await reddit.close()

    # Store duplicate map
    await store_dupmap(dup_map, meta_dir)
    print_reporting(stats)

    if not no_cleanup:
        await cleanup(data_dir, temp_dir)


if __name__ == "__main__":
    start = time.perf_counter()

    init()  # colorama init
    asyncio.run(main())

    for downloader in downloader_registry.values():
        downloader.close()

    elapsed = time.perf_counter() - start
    print(f"{Fore.BLUE}{__file__}{Fore.RESET} executed in {Fore.BLUE}{timedelta(seconds=elapsed)}{Fore.RESET}.")
