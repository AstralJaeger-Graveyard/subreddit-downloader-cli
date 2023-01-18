import json
import re
from enum import Enum
from pathlib import Path

import cdblib
from colorama import Fore


async def async_filter(async_pred, iterable):
    for item in iterable:
        should_yield = await async_pred(item)
        if should_yield:
            yield item


def is_sha256(line: str) -> bool:
    return re.match(r"^[\da-f]{64}", line) is not None


async def load_dupmap(meta_dir: Path) -> dict[str, str]:
    dupfile_path = meta_dir / "dupmap.json"
    if not dupfile_path.exists():
        return {}
    with open(dupfile_path, "r") as dupfile:
        return json.load(dupfile)


async def store_dupmap(dupmap: dict[str, str], meta_dir: Path):
    dupfile_path = meta_dir / "dupmap.json"
    print(f" - {Fore.LIGHTBLACK_EX}Persisting dupmap total elements: {len(dupmap)}{Fore.RESET}")
    with open(dupfile_path, "w") as dupfile:
        json.dump(dupmap, dupfile, indent=2)


class StoreModes(Enum):
    MODE_32 = 1
    MODE_64 = 2





class DuplicateStore(object):

    def __init__(self, meta_folder: Path, name: str, mode: int = 64) -> None:
        self.meta_folder = meta_folder
        self.name = name
        self.store_path = Path(meta_folder, f"store-{name.lower()}.cdb")


    def _create_store(self):
        if not self.store_path.exists():
            with open(self.store_path, 'wb') as f:
                with cdblib.Writer(f) as writer:
                    pass

    def __enter__(self):
        self._create_store()


    def __exit__(self):
        pass