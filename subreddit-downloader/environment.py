import os

from colorama import Fore

from downloaders import BaseDownloader
import environmentlabels as envLbl

HEADERS = 96


def ensure_environment(downloaders: list[BaseDownloader]) -> dict[str, str]:
    """
        Ensures the necessary application environment criteria are met
        :param downloaders: list of enabled downloaders
        :return: a dictionary with all environment variables as string
    """
    environment = dict()
    print("=" * HEADERS)
    print(f"Loading environment".center(HEADERS))

    core_env = {envLbl.REDDIT_CLIENT_ID, envLbl.REDDIT_CLIENT_SECRET}
    optional_env = {envLbl.REDDIT_USERNAME, envLbl.REDDIT_PASSWORD}

    # Core environment:
    environment.update(ensure_environment_namespace(core_env, "core"))

    # Optional environment
    environment.update(ensure_environment_namespace(optional_env, "optional", Fore.LIGHTYELLOW_EX))

    # Downloaders environment:
    print(f"> Loading {Fore.BLUE}downloader{Fore.RESET} environment")
    if len(downloaders) == 0:
        print(f"   No downloaders registered")
    for downloader in downloaders:
        if len(downloader.get_required_env()) == 0:
            print(f" - {Fore.BLUE}{downloader.__class__.__name__}{Fore.RESET} has no environment requirements")
        else:
            environment.update(
                ensure_environment_namespace(
                    set(downloader.get_required_env()),
                    downloader.__class__.__name__,
                    Fore.BLUE)
            )

    return environment


def ensure_environment_namespace(keys: set[str], namespace: str, color: str = Fore.YELLOW) -> dict[str, str]:
    print(f"> Loading {Fore.YELLOW}{namespace}{Fore.RESET} environment")
    any_nok = False
    env: dict[str, str] = dict()

    for key in keys:
        if key not in os.environ.keys() or os.environ[key] == "":
            print(f" - ensuring {color}{namespace}.{key}{Fore.RESET}: {Fore.RED}NOK{Fore.RESET}")
            any_nok = key
        else:
            print(f" - ensuring {color}{namespace}.{key}{Fore.RESET}: {Fore.GREEN}OK{Fore.RESET}")
            env[key] = os.environ[key]
    raise_for_any_nok(any_nok)
    return env


def raise_for_any_nok(any_nok: bool) -> None:
    print("")
    if any_nok:
        raise ValueError(f"Key {Fore.RED}{any_nok}{Fore.RESET} not found")