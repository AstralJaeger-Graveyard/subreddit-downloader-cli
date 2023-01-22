import functools
import json
import re
import sqlite3
import time
from pathlib import Path

from colorama import Fore
from asyncpraw.models import Submission

HEADERS = 96


async def async_filter(async_pred, iterable):
    for item in iterable:
        should_yield = await async_pred(item)
        if should_yield:
            yield item


def is_sha256(line: str) -> bool:
    return re.match(r"^[\da-f]{64}", line) is not None


def retry(max_retries = 5):
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as error:
                    print(f"Error {error} while executing {func.__name__} retrieing {max_retries - retries} more times")
                    retries += 1

        return wrapper

    return decorator_retry


times_store: dict[str, list[int]] = dict()


def timeit(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter_ns()
        result = func(*args, **kwargs)
        delta = time.perf_counter_ns() - start

        if func.__name__ in times_store:
            times_store.get(func.__name__).append(delta)
        else:
            times_store.update({func.__name__: [delta]})
        average = sum(times_store.get(func.__name__)) / len(times_store.get(func.__name__)) / 1_000_000
        print(f"Function {func.__name__} Took {delta / 1_000_000:.4f}s AVG: {average:.4f}s")
        return result
    return wrapper


class SubmissionStore(object):
    store_version = "1"  # In order to prevent reading older store versions

    def __init__(self, meta_folder: Path) -> None:
        self.meta_folder = meta_folder
        self.store_path = Path(meta_folder, f"subission_store_v{self.store_version}.sqlite")

        try:
            self.connection = sqlite3.connect(self.store_path)
        except Exception as e:
            print(e)
            raise e

        self.created_cache: set[str] = set()

    def __get_table_name(self, display_name: str) -> str:
        return "sr_" + re.sub(r"\W+", "", display_name).lower()

    def __define_schema(self, display_name: str) -> None:
        """ Private method to define the database schema """
        table_name = self.__get_table_name(display_name)
        if table_name not in self.created_cache:
            self.connection.execute(f"CREATE TABLE IF NOT EXISTS {table_name}("
                                    "submission_id TEXT PRIMARY KEY, "
                                    "submission_title TEXT NOT NULL, "
                                    "submission_created_utc INTEGER"
                                    ")"
                                    )
            self.connection.commit()
            self.created_cache.add(table_name)

    def add_submission(self, submission: Submission, display_name: str) -> int | None:
        self.__define_schema(display_name)
        table_name = self.__get_table_name(display_name)
        sql = f'''INSERT INTO {table_name}(submission_id, submission_title, submission_created_utc) VALUES(?,?,?)'''
        cur = self.connection.cursor()
        cur.execute(sql, (submission.id, submission.title, int(submission.created_utc)))
        self.connection.commit()
        return cur.lastrowid

    def has_submission(self, submission_id: str, display_name: str) -> bool:
        self.__define_schema(display_name)
        sql = f'''SELECT * FROM {self.__get_table_name(display_name)} WHERE submission_id=?'''
        cur = self.connection.cursor()
        cur.execute(sql, (submission_id,))
        if cur.fetchone():
            return True
        return False

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.connection.close()
