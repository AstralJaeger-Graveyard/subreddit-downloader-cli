import asyncio
import os
from asyncio import TaskGroup
from pathlib import Path

from colorama import Fore, Back, Style
from utils import HEADERS


async def cleanup_temp(temp_dir: Path) -> None:
    """ Clean up temp dir, remove all files that might be stuck there """
    print(f"> Cleaning up temp dir: {temp_dir}")
    for file_path in os.listdir(temp_dir):
        print(f" - Removing temp file: {file_path}")
        os.remove(file_path)


async def cleanup_data(data_dir: Path) -> None:
    """ Clean up data dir """
    pass


async def cleanup(data_dir: Path, temp_dir: Path) -> None:
    print(f"> {Fore.BLUE}Cleaning up folder{Fore.RESET}  : {data_dir}")
    print(f"> {Fore.BLUE}Temp. folder{Fore.RESET} : {temp_dir}")
    print("=" * HEADERS)

    file_map: dict[int, str] = dict()
    async with TaskGroup() as tg:
        tg.create_task(cleanup_temp(temp_dir))
        tg.create_task(cleanup_data(data_dir))

    print(f"File map contained {len(file_map)} elements")