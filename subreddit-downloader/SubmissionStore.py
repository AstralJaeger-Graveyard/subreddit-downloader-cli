import asyncio
import platform
from asyncio import TaskGroup
from pathlib import Path

from asyncpraw import Reddit
from asyncpraw.models import Submission, Subreddit
from utils import SubmissionStore


async def handle_submission(submission: Submission, store: SubmissionStore) -> None:
    # print(f"{submission.id}: {submission.title}")
    subreddit = submission.subreddit
    store.add_submission(submission, subreddit.display_name)


async def main():
    reddit = Reddit(
            client_id = "4ag021TW-BUYPv9mT4LG0A",
            client_secret = "s9sf_N0HJcHBBWMDHbDH_tLloa3wKQ",
            username = "AstralJaegerBot",
            password = "Provider_Manger4_Reseller_Uranium",
            user_agent = f"{platform.system().lower()}:sr-downloader-cli:0.0.999 (by u/97hilfel)"
            )

    subreddit = await reddit.subreddit("slut")

    with SubmissionStore(Path("./")) as store:
        async with TaskGroup() as tg:
            async for submission in subreddit.stream.submissions():
                if not store.has_submission(submission.id, subreddit.display_name):
                    tg.create_task(handle_submission(submission, store))


if __name__ == "__main__":
    asyncio.run(main())