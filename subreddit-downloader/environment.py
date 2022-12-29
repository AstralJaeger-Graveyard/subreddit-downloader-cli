import os

from colorama import Fore

from downloaders import BaseDownloader
from environmentlabels import *

HEADERS = 96


def ensure_environment(downloaders: list[BaseDownloader]) -> dict[str, str]:
    """
    Ensures the necessary application environment criteria are met
    :param downloaders: which downloaders are enabled
    :return: a dictionary with all environment strings
    """
    environment = dict()
    any_nok = None

    print("=" * HEADERS)
    print(f"Loading environment".center(HEADERS))

    # Core Environment:
    keys = [REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET]
    print(f"> Loading {Fore.YELLOW}core{Fore.RESET} environment")
    for key in keys:
        if key not in os.environ.keys() or os.environ[key] == "":
            print(f" - ensuring {Fore.YELLOW}core.{key}{Fore.RESET}: {Fore.RED}NOK{Fore.RESET}")
            any_nok = key
        else:
            print(f" - ensuring {Fore.YELLOW}core.{key}{Fore.RESET}: {Fore.GREEN}OK{Fore.RESET}")
            environment[key] = os.environ[key]

    # Downloaders environment:
    print(f"> Loading {Fore.BLUE}downloader{Fore.RESET} environment")
    if len(downloaders) == 0:
        print(f"   No downloaders registered")
    for downloader in downloaders:
        if len(downloader.get_required_env()) == 0:
            print(f" - {Fore.BLUE}{downloader.__class__.__name__}{Fore.RESET} has no environment requirements")

        for key in downloader.get_required_env():
            if key not in os.environ.keys():
                print(f" - ensuring {Fore.BLUE}{downloader.__class__.__name__}.{key}{Fore.RESET}: {Fore.RED}NOK{Fore.RESET}")
                any_nok = f"{downloader.__class__.__name__}.{key}"
            else:
                print(f" - ensuring {Fore.BLUE}{downloader.__class__.__name__}.{key}{Fore.RESET}: {Fore.GREEN}OK{Fore.RESET}")
                environment[key] = os.environ.get(key)
    print("")
    if any_nok is not None:
        raise ValueError(f"Key {Fore.RED}{any_nok}{Fore.RESET} not found")
    return environment
