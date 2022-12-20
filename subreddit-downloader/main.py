import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta
import os
import os.path
import sys
import platform
import mimetypes
import hashlib
from tempfile import SpooledTemporaryFile

from sentry_sdk import init as sentry_init, start_span, start_transaction, set_tag, set_user, set_extra, set_level, set_context
import asyncpraw
import requests
from colorama import init, Fore, Back, Style

sentry_init(
    dsn="https://3b39db99682e4801885ee7db3f28f802@o1319955.ingest.sentry.io/4504361285844992",
    traces_sample_rate=1.0,
)

HEADERS = 96
LIMIT = 10000
TMP = os.environ["TEMP_LOC"]
os.makedirs(TMP, exist_ok=True)


async def generic_download(url: str, target: str) -> str:
    with start_span(op="generic_download", description="Download file from unknown source") as span:
        span.set_tag("req.host", url)
        with requests.get(url, stream=True) as req:
            span.set_tag("request.status_code", req.status_code)
            span.set_tag("request.content_type", req.headers["content-type"])
            span.set_tag("request.length", len(req.content))
            req.raise_for_status()

            # ext alreaady has the dot
            ext = mimetypes.guess_extension(req.headers["content-type"])
            if ext is None:
                return f"{Fore.YELLOW}No supported content found CT: {req.headers['content-type']}{Fore.RESET}"

            with SpooledTemporaryFile(512 * 1025 * 1024, "wb", dir=TMP) as tmp_file:
                shagen = hashlib.sha256()
                for chunk in req.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                    shagen.update(chunk)
                tmp_file.seek(0)
                hex_digest = shagen.hexdigest()
                filepath = os.path.join(target, f"{hex_digest}{ext}")
                if not os.path.exists(filepath):
                    with open(filepath, "wb") as persistent_file:
                        shutil.copyfileobj(tmp_file, persistent_file)
                span.set_tag("file_hash", hex_digest)
                return hex_digest


async def redgifs_download(url: str, target: str) -> str:
    with start_span(op="redgifs_download", description="Download file from redgifs") as span:
        try:
            span.set_tag("req.host", url)
            content_id = url.split('/watch/', 1)[1]
        except IndexError:
            print(f"  Failed with url: {Fore.GREEN}{url}{Fore.RESET} | {url.split('/watch/', 1)}")
            return ""

        session = requests.Session()
        req = session.get("https://api.redgifs.com/v2/auth/temporary")
        if req.status_code != 200:
            return ""

        auth_json = req.json()
        token = auth_json["token"]
        headers = {
            "Authorization": f"Bearer {token}"
        }

        req = session.get(f"https://api.redgifs.com/v2/gifs/{content_id}", headers=headers)
        if req.status_code != 200:
            return ""

        raw = req.json()
        content_url = raw["gif"]["urls"]["hd"]

        with session.get(content_url, headers=headers, stream=True) as req:
            span.set_tag("request.status_code", req.status_code)
            span.set_tag("request.content_type", req.headers["content-type"])
            span.set_tag("request.length", len(req.content))
            req.raise_for_status()
            # ext alreaady has the dot
            ext = mimetypes.guess_extension(req.headers["content-type"])
            if ext is None:
                return "No supported content found"

            with tempfile.SpooledTemporaryFile(512*1025*1024, "wb", dir=TMP) as tmp_file:
                shagen = hashlib.sha256()
                for chunk in req.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                    shagen.update(chunk)
                tmp_file.seek(0)
                hex_digest = shagen.hexdigest()
                filepath = os.path.join(target, f"{hex_digest}{ext}")
                if not os.path.exists(filepath):
                    with open(filepath, "wb") as persistent_file:
                        shutil.copyfileobj(tmp_file, persistent_file)
                span.set_tag("file_hash", hex_digest)
                return hex_digest


# TODO: Add imgur support
async def download(url: str, target: str) -> str:
    with start_transaction(op="download", name=url):
        if "redgifs" in url:
            return await redgifs_download(url, target)
        if "imgur" in url:
            return f"{Fore.RED}Imgur is not supported{Fore.RESET}"
        elif "pximg" in url:
            return f"{Fore.RED}Pixiv is not supported{Fore.RED}"
        elif "discordapp" in url:
            return f"{Fore.RED}Discord CDN is not supported{Fore.RED}"
        else:
            try:
                return await generic_download(url, target)
            except requests.exceptions.RequestException:
                return f"{Fore.RED}Generic download exception ocurred at host:{Fore.RED} {url}"


async def main(args: list[str]):

    print("=" * HEADERS)
    print(f"{Fore.MAGENTA}Subreddit CLI Downloader{Fore.RESET} V0.1.0".center(HEADERS))
    print("=" * HEADERS)
    print("")


    reddit = asyncpraw.Reddit(
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"],
        user_agent=f"{platform.platform()}:SR-Downloader-CLI:0.1.0 (by u/97hilfel)",
        username=os.environ["USERNAME"],
        password=os.environ["PASSWORD"]
    )

    subreddit_name = args[1]
    subreddit = await reddit.subreddit(subreddit_name)

    target_folder = f"ws-{subreddit.display_name}"
    target = os.path.join(os.environ["DATA_LOC"], target_folder)
    os.makedirs(target, exist_ok=True)
    print(f"> {Fore.BLUE}Target folder{Fore.RESET}: {target}")
    print(f"> {Fore.BLUE}Args{Fore.RESET}: {args}")
    print(f"> {Fore.BLUE}Subreddit{Fore.RESET}: r/{Fore.RED}{subreddit.display_name}{Fore.RESET}")
    print(f"> {Fore.BLUE}Limit{Fore.RESET}: {LIMIT}")

    idx: int = 1
    async for submission in subreddit.new(limit=LIMIT):
        await submission.load()
        score_color = Fore.GREEN if submission.score > 0 else Fore.RED
        created = datetime.fromtimestamp(submission.created_utc)
        hash = ""
        if not submission.is_self:
            hash = await download(submission.url, target)
        print(f" - {Fore.BLUE}{idx:3}{Fore.RESET}. [{score_color}{submission.score:4}{Fore.RESET}] <{created}> {submission.title} [{hash}]")
        idx += 1

    await reddit.close()

if __name__ == "__main__":
    import time
    init()
    start = time.perf_counter()
    asyncio.run(main(sys.argv))
    elapsed = time.perf_counter() - start
    print(f"{Fore.BLUE}{__file__}{Fore.RESET} executed in {Fore.BLUE}{timedelta(seconds=elapsed)}{Fore.RESET} seconds.")
