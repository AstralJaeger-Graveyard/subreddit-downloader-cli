import json
import re
from pathlib import Path
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

