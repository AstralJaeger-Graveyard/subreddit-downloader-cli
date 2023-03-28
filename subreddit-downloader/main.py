import argparse
import asyncio
import datetime
import math
import os
import os.path
import platform
import re
import time
import typing
import urllib.parse
from asyncio import TaskGroup
from collections import Counter
from datetime import timedelta
from pathlib import Path
from contextlib import asynccontextmanager

import asyncprawcore.exceptions
import requests
from asyncpraw import Reddit
from asyncpraw.models import Submission, Subreddit
from asyncprawcore.exceptions import ResponseException
from colorama import init, Fore
from retry import retry

import environmentlabels as envlbl
from downloaders import BaseDownloader, SimpleDownloader, RedditDownloader, RedgifsDownloader, ImgurDownloader, \
    GfycatDownloader, \
    NoDownloaderException
from environment import ensure_environment
from urlresolvers import StandardUrlResolver, CrosspostUrlResolver
from utils import SubmissionStore, HEADERS
from cleanup import cleanup

# Constants
VERSION = "0.5.0"
LIMIT = 1000

generic_downloader = SimpleDownloader()

# Register downloaders
used_downloaders = [
    generic_downloader,
    RedditDownloader(),
    RedgifsDownloader(),
    ImgurDownloader(),
    GfycatDownloader()
]

# Important environment
env = ensure_environment(used_downloaders)
downloader_registry: dict[re.Pattern, BaseDownloader] = {}

stats: Counter = Counter()


async def download(url: str, target: Path, prefix: str = "") -> (str, Path):
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

    if match_str is None:
        return ("", None)

    # Count used hosts
    stats.update([match_str])

    for provider in downloader_registry.keys():
        if re.match(provider, match_str):
            return await downloader_registry[provider].download(url, target, prefix)

    raise NoDownloaderException


def store_submission(store: SubmissionStore, submission: Submission) -> None:
    if not store.has_submission(submission.id):
        store.add_submission(submission)


async def handle_text(submission: Submission, subreddit: Subreddit, store: SubmissionStore, target_dir: str,
                      jobid: int) -> None:
    submission_id = submission.id
    score_color = Fore.GREEN if submission.score > 0 else Fore.RED
    title = submission.title
    text = submission.selftext
    author = submission.author
    created = datetime.datetime.fromtimestamp(submission.created_utc)
    subreddit = subreddit.display_name

    sanitized_title = title.lower() \
        .replace(' ', '_') \
        .replace('-', '_')
    sanitized_title = re.sub(r'\W+', '', sanitized_title)

    if len(sanitized_title) > 127:
        sanitized_title = sanitized_title[:127]

    filename = f"{submission_id}_{sanitized_title}.md"
    filepath = Path(target_dir, filename)
    if filepath.exists():
        print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
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

    print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] " +
          f"{submission.title} [{filename}]")
    store_submission(store, submission)
    store.add_file(filename, submission)


async def handle_url(url: str, submission: Submission, store: SubmissionStore, target_dir: str, jobid: int,
                     file_prefix: str = "") -> None:
    score_color = Fore.GREEN if submission.score > 0 else Fore.RED
    prefix = f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}]"
    try:
        digest, filepath = await download(url, target_dir, file_prefix)
        if digest == "" and filepath is None:
            print(f"{prefix} {submission.title}")
        else:
            print(f"{prefix} {submission.title} [{digest}]")
            filepath_str = f"{filepath}"
            filename = filepath_str[filepath_str.rfind("/"):]
            store.add_file(filename, submission)
        # Only add submission if download was successful
        store_submission(store, submission)
    except NoDownloaderException:
        print(f"{prefix} No downloader for url: {Fore.YELLOW}{url}{Fore.RESET}")
    except requests.exceptions.HTTPError as http_error:
        print(f"{prefix} HTTP Error {Fore.YELLOW}{http_error}{Fore.RESET} for url: {Fore.YELLOW}{url}{Fore.RESET}")
        if hasattr(http_error.response, "status_code") and http_error.response.status_code == 404:
            store_submission(store, submission)  # Data was probably deleted, no need to revisit
    except TypeError as type_error:
        raise type_error
    except Exception as error:
        print(
            f"{prefix} {Fore.RED}{error.__class__.__name__}{Fore.RESET} {Fore.YELLOW}{error}{Fore.RESET} for url: {Fore.YELLOW}{url}{Fore.RESET}")


async def handle_submission(submission: Submission, subreddit: Subreddit, reddit: Reddit, store: SubmissionStore,
                            target_dir: Path, jobid: int) -> None:
    try:
        if submission.is_self:
            await handle_text(submission, subreddit, store, target_dir, jobid)
        elif hasattr(submission, "crosspost_parent") and submission.crosspost_parent is not None:
            urls = await CrosspostUrlResolver(reddit).resolve(submission)
            for url in urls:
                await handle_url(url, submission, store, target_dir, jobid)
        else:
            urls = await StandardUrlResolver(reddit).resolve(submission)
            prefix = submission.id if len(urls) > 1 else ""
            for url in urls:
                await handle_url(url, submission, store, target_dir, jobid, prefix)
    except Exception as error:
        print(f" - {Fore.BLUE}{jobid:3}{Fore.RESET}. Critical Error {Fore.RED}{error}{Fore.RESET} for submission: " +
              f"{Fore.RED}{submission.permalink}{Fore.RESET}")
        raise error


@retry(tries=10, delay=10, backoff=1.5)
async def submission_task_producer(taskgroup: TaskGroup, subreddit: Subreddit, reddit: Reddit,
                                   store: SubmissionStore, target_dir: Path, start_time: float) -> None:
    jobid: int = 1  # Actual jobs that get downloaded
    taskid: int = 1  # Jobs that get checked but have already been downloaded
    steps = 10 if LIMIT <= 20 else 25
    reporting_steps = int(math.ceil(LIMIT / steps))
    async for submission in subreddit.new(limit=LIMIT):
        if not store.has_submission(submission.id):
            attempt = 0
            while attempt < 5:
                try:
                    attempt += 1
                    await submission.load()
                    break
                except asyncprawcore.exceptions.RequestException as error:
                    wait_time = 10 * attempt
                    print(f"An error occurred {Fore.RED}{error}{Fore.RESET} waiting for {wait_time}s.")
                    await asyncio.sleep(wait_time)
            taskgroup.create_task(handle_submission(submission, subreddit, reddit, store, target_dir, jobid))
            jobid += 1
        if taskid % reporting_steps == 0:
            print(" " * 3 +
                  f"{Fore.CYAN}Progress: approximately {round((taskid / LIMIT) * 100):2}% done." +
                  f" took {timedelta(seconds=(time.perf_counter() - start_time))} so far{Fore.RESET}")
        taskid += 1
    store.explicit_commit()


async def handle_subreddit(subreddit: Subreddit, reddit: Reddit, data_dir: Path, meta_dir: Path) -> None:
    start_time = time.perf_counter()
    target_dir = Path(data_dir, f"ws-{subreddit.display_name.lower()}")

    if not target_dir.exists():
        os.makedirs(target_dir, exist_ok=True)

    print("=" * HEADERS)
    print(f"> {Fore.BLUE}Subreddit{Fore.RESET}    : r/{Fore.RED}{subreddit.display_name}{Fore.RESET}")
    print(f"> {Fore.BLUE}Target folder{Fore.RESET}: {target_dir}")
    print("=" * HEADERS + os.linesep)

    with SubmissionStore(meta_dir) as store:
        async with asyncio.TaskGroup() as taskGroup:
            await submission_task_producer(taskGroup, subreddit, reddit, store, target_dir, start_time)

    end_time = time.perf_counter()
    print(f"> Downloading subreddit took {Fore.BLUE}{timedelta(seconds=(end_time - start_time))}{Fore.RESET}")


async def prefetch_subreddits(reddit: Reddit, sr_names: list[str]) -> list[Subreddit]:
    """
        This function will convert a list of subreddit names to a list of loaded subreddit's
        Params:
            reddit (Reddit): The reddit instance
            sr_names (list[str]): A list of subreddit names
        Returns
            subreddits (list[Subreddit]): A list of loaded, verified subreddit's
    """

    print("Preparing Subreddit's for download:")
    subreddits = list()
    for sr_name in sr_names:
        try:
            subreddit = await reddit.subreddit(sr_name)
            # Subreddit needs to be loaded in order to trigger an exception in case it has been banned or is nor private
            await subreddit.load()
            print(f"    - r/{Fore.GREEN}{subreddit.display_name + Fore.RESET:.<25}: ✔️")
            subreddits.append(subreddit)
        except ResponseException:
            print(f"    - r/{Fore.RED}{sr_name + Fore.RESET:.<25}: ❌ (Might be deleted, banned or private)")
    return subreddits


def build_subreddit_list(arg_subreddits: list[str], refresh_mode: bool, data_dir: Path) -> list[str]:
    """
        This function builds a list of subreddit names in following order:
        - Subreddits passed via CLI to ensure they get downloaded first
        - Existing subreddits in the workspace if refresh_mode is enabled
        params:
            - refresh_mode (bool): If refresh_mode is enabled
            - arg_subreddits (list[str]): The list of subreddits passed via CLI
            - data_dir (Path): The data_dir to check for existing subreddits
        returns:
            sr_names (list[str]): A list of subreddit names.
    """
    if arg_subreddits is None or len(arg_subreddits) == 0:
        sr_names = list()
    else:
        sr_names = list(arg_subreddits)

    if refresh_mode:
        print("No subreddit names passed, looking for existing resources and refreshing existing resources")
        existing = data_dir.glob("ws-*")
        sr_names += sorted([srn.name.replace("ws-", "") for srn in existing])
    return sr_names


def print_progress(subreddits: list[Subreddit], idx: int) -> None:
    print(f"> r/{Fore.LIGHTBLUE_EX}{subreddits[idx - 1] if idx > 0 else 'FIRST'}{Fore.RESET} >> " +
          f"r/{Fore.CYAN}{subreddits[idx].display_name}{Fore.RESET} >> " +
          f"r/{Fore.BLUE}{subreddits[idx + 1] if idx + 1 < len(subreddits) else 'LAST'}{Fore.RESET}")
    print(f"> {Fore.CYAN}{round((1 - (idx + 1) / len(subreddits)) * 100)}{Fore.RESET}% remaining")


@asynccontextmanager
async def reddit_handler(environment: dict[str, str]) -> typing.AsyncGenerator:
    if environment[envlbl.REDDIT_USERNAME] and environment[envlbl.REDDIT_PASSWORD]:
        reddit = Reddit(
            client_id=environment[envlbl.REDDIT_CLIENT_ID],
            client_secret=environment[envlbl.REDDIT_CLIENT_SECRET],
            username=environment[envlbl.REDDIT_USERNAME],
            password=environment[envlbl.REDDIT_PASSWORD],
            user_agent=f"{platform.system().lower()}:{envlbl.REDDIT_CLIENT_ID}:{VERSION} (by u/97hilfel)"
        )
    else:
        reddit = Reddit(
            client_id=environment[envlbl.REDDIT_CLIENT_ID],
            client_secret=environment[envlbl.REDDIT_CLIENT_SECRET],
            user_agent=f"{platform.system().lower()}:{envlbl.REDDIT_CLIENT_ID}:{VERSION} (by u/97hilfel)"
        )
    yield reddit
    await reddit.close()


def build_downloader_registry(downloaders: list[BaseDownloader], no_op: bool = False) -> dict[
    re.Pattern, BaseDownloader]:
    registry: dict[re.Pattern, BaseDownloader] = dict()
    for dl in downloaders:
        dl.init(env, no_op)
        print(
            f"> {Fore.BLUE}{dl.__class__.__name__}{Fore.RESET} supports {len(dl.get_supported_domains())} providers")
        for host_pattern in dl.get_supported_domains():
            registry[host_pattern] = dl
    return registry


def is_supported(url: str, registry: dict[re.Pattern, BaseDownloader]) -> bool:
    return any(p.match(url) is not None for p in registry.keys())


def print_reporting(reporting_stats: dict[str, int], registry: dict[re.Pattern, BaseDownloader]) -> None:
    """
        Prints a reporting to STDOUT
        Params:
            stats (Counter): The counter object to print
    """
    print("=" * HEADERS)
    total_calls = sum(reporting_stats.values())
    print(f"Used providers and cdn's over {total_calls} attempted downloads:")

    for key, value in sorted(reporting_stats.items(), key=lambda item: item[1], reverse=True):
        color = Fore.GREEN if is_supported(key, registry) else Fore.RED
        percentage = round(value / total_calls * 100, 2)
        print(f" - {Fore.BLUE}{key + Fore.RESET:.<48}: {value: 4} <{color}{percentage:4.1f}%{Fore.RESET}>")
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
    print("Application startup successful, environment loaded".center(HEADERS))
    print("=" * HEADERS)
    print("")

    # Initialize argparse
    global LIMIT, downloader_registry

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
    arg_srs = p_args.subreddits

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
    downloader_registry = build_downloader_registry(used_downloaders, no_op)

    print("")
    print(f"> {Fore.BLUE}Data folder{Fore.RESET}  : {data_dir}")
    print(f"> {Fore.BLUE}Temp. folder{Fore.RESET} : {temp_dir}")
    print(f"> {Fore.BLUE}Meta. folder{Fore.RESET} : {meta_dir}")
    print(f"> {Fore.BLUE}Limit{Fore.RESET}        : {LIMIT}")

    async with reddit_handler(env) as reddit:
        subreddits = await prefetch_subreddits(reddit, build_subreddit_list(arg_srs, refresh_mode, data_dir))
        for idx, sr in enumerate(subreddits):
            print_progress(subreddits, idx)
            await handle_subreddit(sr, reddit, data_dir, meta_dir)

    # Store duplicate map
    print_reporting(stats, downloader_registry)

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
