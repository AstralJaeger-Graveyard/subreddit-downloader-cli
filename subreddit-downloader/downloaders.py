import mimetypes
import re
import shutil
from hashlib import sha256
from os import path, PathLike
from pathlib import Path
from re import Pattern
from tempfile import SpooledTemporaryFile
from urllib.parse import urlparse

import fleep
import requests
from colorama import Fore
from requests import Response

from environmentlabels import *


class DuplicateFileException(Exception):
    pass


class NoDownloaderException(Exception):
    pass


class BaseDownloader:
    """
        Defines the base downloader and provides utilities to save ``Response`` data to disk with a unique filename.
    """

    def __init__(self):
        self.no_op = False
        self.environment: dict[str, str] = {}
        pass

    def init(self, environment: dict[str, str], no_op: bool = False) -> None:
        self.no_op = no_op
        self.environment = environment

    def get_supported_domains(self) -> list[Pattern]:
        """
            Returns a list with supported domains
        """
        return []

    def get_required_env(self) -> list[str]:
        return []

    async def download(self, url, target) -> (str, Path):
        pass

    def save_to_disk(self, response: Response, target: str | PathLike) -> (str, Path):
        with SpooledTemporaryFile(512 * 1025 * 1024, "wb", dir=self.environment[TEMP_LOCATION]) as tmp_file:
            shagen = sha256()
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
                shagen.update(chunk)
            tmp_file.seek(0)

            ext = mimetypes.guess_extension(response.headers["content-type"])
            if ext == "" or ext is None:
                # Fleep seems to be quite slow, guess the extension if possible
                ext = fleep.get(tmp_file.read(128)).extension
                tmp_file.seek(0)
            ext = ext.replace(".", "")

            digest = shagen.hexdigest()
            if ext is None or ext == "xsl":
                return digest, None

            filepath = Path(target, f"{digest}.{ext}")
            if path.exists(filepath):
                return "", filepath
            if not self.no_op:
                with filepath.open("wb") as persistent_file:
                    shutil.copyfileobj(tmp_file, persistent_file)
            return digest, filepath

    def close(self) -> None:
        pass


class GenericDownloader(BaseDownloader):
    """
        A generic downloader that downloads any file, might not work in most cases
    """

    def __init__(self):
        super().__init__()

    def get_supported_domains(self) -> list[Pattern]:
        return [
            re.compile(r"^(wimg\.)?rule34\.xxx"),
            re.compile(r"^(wimg\.)?rule34\.us"),
            re.compile(r"^d\.furaffinity\.net"),
            re.compile(r"^(static\d\.)?e621\.net"),
            re.compile(r"^(w\.)?wallhaven\.cc"),
            re.compile(r"^(i\.)?ibb\.co"),
            re.compile(r"^(lotus\.)?paheal\.net"),
            re.compile(r"^(img\d\.)?gelbooru\.com"),
            re.compile(r"^(d\.)?facdn\.net"),
            re.compile(r"^(cdn[a-z\d]\.)?artstation\.com"),
            re.compile(r"^(art\.)?ngfiles\.com"),
            re.compile(r"^(pictures\.)?hentai-foundry\.com"),
            re.compile(r"^(media\.)?discordapp\.(net)?(com)?"),
            re.compile(r"^(cdn\.)?discordapp\.(net)?(com)?"),
            re.compile(r"^(files\.)catbox\.moe"),
            re.compile(r"^(file\.)coffee"),
            re.compile(r"simoneluxe\.com"),
            re.compile(r"uploadir\.com"),
            re.compile(r"i\.postimg\.cc"),
            re.compile(r"dl\.phncdn\.com"),
            re.compile(r"([it]\d\.)nhentai\.net"),
            re.compile(r"(sun\d-\d\.)?userapi\.com"),
            re.compile(r"(\d+\.)?(media\.)?tumblr\.com"),  # Tumblr
            re.compile(r"^(scontent\.)?(fbne\d-\d\.)?(fna\.)fbcdn.net"),  # Facebook CDN
            re.compile(r"^(i\.)?pinimg.com"),  # Pinterest CDN
            re.compile(r"^(images-wixmp-[\da-f]*\.)?wixmp.com")  # WIX CDN
        ]

    def get_required_env(self) -> list[Pattern]:
        return []

    async def download(self, url, target) -> (str, Path):
        with requests.get(url) as response:
            response.raise_for_status()
            return self.save_to_disk(response, target)


class RedditDownloader(BaseDownloader):
    """
        A downloader that provides support for reddit
    """

    def __init__(self):
        BaseDownloader.__init__(self)

    def get_supported_domains(self) -> list[Pattern]:
        return [
            re.compile(r"^i\.redd\.it"),
            re.compile(r"^preview\.redd\.it")
        ]

    def get_required_env(self) -> list[str]:
        return []

    async def download(self, url, target) -> (str, Path):
        with requests.get(url) as response:
            response.raise_for_status()
            return self.save_to_disk(response, target)


class RedgifsDownloader(BaseDownloader):
    """
        A downloader that provides support for redgifs.com
    """

    def __init__(self):
        super().__init__()
        self.__session = requests.Session()
        self.__auth = {}

    def init(self, environment: dict[str, str], no_op: bool = False) -> None:
        super().init(environment, no_op)
        with self.__session.get("https://api.redgifs.com/v2/auth/temporary") as response:
            response.raise_for_status()
            self.__auth = response.json()

    def get_supported_domains(self) -> list[Pattern]:
        return [
            re.compile(r"(www\.)?redgifs\.com"),
            re.compile(r"(v\d\.)redgifs\.com"),
            re.compile(r"(i\.)redgifs\.com")
        ]

    def get_required_env(self) -> dict[str, type]:
        return {}

    async def download(self, url, target) -> (str, Path):
        try:
            content_id = self._parse_content_id(url)
        except IndexError:
            return f"{Fore.YELLOW}Could not parse: {url}{Fore.RESET}"

        headers = {
            "Authorization": f"Bearer {self.__auth['token']}",
            "Accept": "application/json"
        }
        with self.__session.get(f"https://api.redgifs.com/v2/gifs/{content_id}", headers=headers) as response:
            response.raise_for_status()
            data = response.json()  # Consider to persist data json somewhere
            with self.__session.get(data["gif"]["urls"]["hd"], headers=headers, stream=True) as video_response:
                return self.save_to_disk(video_response, target)

    def _parse_content_id(self, url: str) -> str:
        if "i.redgifs.com" in url:
            return url.split("/i/", 1)[1]
        else:
            return url.split("/watch/", 1)[1]

    def close(self) -> None:
        self.__session.close()


class ImgurDownloader(BaseDownloader):
    """
        A downloader that provides support for imgur.com
    """

    def __init__(self):
        super().__init__()
        self.__session = requests.Session()
        self.__auth = {}

    def init(self, environment: dict[str, str], no_op: bool = False) -> None:
        super().init(environment, no_op)
        self.__auth = {
            "Authorization": f"Client-ID {environment[IMGUR_CLIENT_ID]} "
        }

    def get_supported_domains(self) -> list[Pattern]:
        # urls are i.imgur.com or sometimes l.imgur.com
        return [re.compile("([il]\\.)?imgur\\.com")]

    def get_required_env(self) -> list[str]:
        return ["imgur_cid"]

    async def download(self, url, target) -> (str, Path):
        content_id = self._parse_content_id(url)
        with self.__session.get(f"https://api.imgur.com/3/image/{content_id}", headers=self.__auth,
                                stream=True) as data_response:
            data_response.raise_for_status()
            data = data_response.json()["data"]
            content_link = data["link"]
            if hasattr(data, "in_gallery") and data["in_gallery"]:
                print(f"{' ' * 18} URL: {url} is in gallery: {data['in_gallery']}")
            with self.__session.get(content_link, headers=self.__auth, stream=True) as content_response:
                return self.save_to_disk(content_response, target)

    def _parse_content_id(self, url: str) -> str:

        if url.startswith("i"):
            # handle image
            last_slash_pos = url.rfind("/") + 1
            dot_pos = url.rfind(".") if "." in url[last_slash_pos:] else len(url)
            filename = url[last_slash_pos: dot_pos]
        else:
            o = urlparse(url)
            url_path = o.path
            if url_path.endswith("/"):
                url_path = url_path[:len(url_path) - 1]
            id_str: str = url_path[url_path.rfind("/") + 1:]
            if "." in id_str:
                return id_str.split(".")[0]
            return id_str

    def close(self) -> None:
        self.__session.close()


class GfycatDownloader(BaseDownloader):
    """
        A downloader that provides support for gfycat.com
    """

    def __init__(self):
        super().__init__()
        self.__session = requests.Session()
        self.__auth = {}

    def init(self, environment: dict[str, str], no_op: bool = False) -> None:
        super().init(environment, no_op)
        self.__auth = {
            "Authorization": f"Client-ID {environment[IMGUR_CLIENT_ID]} "
        }

    def get_supported_domains(self) -> list[Pattern]:
        # urls are i.imgur.com or sometimes l.imgur.com
        return [re.compile("([il]\\.)?imgur\\.com")]

    def get_required_env(self) -> list[str]:
        return [GFYCAT_CLIENT_ID, GFYCAT_CLIENT_SECRET]

    async def download(self, url, target) -> (str, Path):
        content_id = self._parse_content_id(url)
        with self.__session.get(f"https://api.imgur.com/3/image/{content_id}", headers=self.__auth,
                                stream=True) as data_response:
            data_response.raise_for_status()
            data = data_response.json()["data"]
            content_link = data["link"]
            if hasattr(data, "in_gallery") and data["in_gallery"]:
                print(f"{' ' * 18} URL: {url} is in gallery: {data['in_gallery']}")
            with self.__session.get(content_link, headers=self.__auth, stream=True) as content_response:
                return self.save_to_disk(content_response, target)

    def _parse_content_id(self, url: str) -> str:

        if url.startswith("i"):
            # handle image
            last_slash_pos = url.rfind("/") + 1
            dot_pos = url.rfind(".") if "." in url[last_slash_pos:] else len(url)
            filename = url[last_slash_pos: dot_pos]
        else:
            o = urlparse(url)
            url_path = o.path
            if url_path.endswith("/"):
                url_path = url_path[:len(url_path) - 1]
            id_str: str = url_path[url_path.rfind("/") + 1:]
            if "." in id_str:
                return id_str.split(".")[0]
            return id_str

    def close(self) -> None:
        self.__session.close()
