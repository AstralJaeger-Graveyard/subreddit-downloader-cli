import datetime
import mimetypes
import os
import re
import shutil
import time
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

import environmentlabels as envLbl

# This link points to this GitHub Gist that contains a list of regex to websites
# that can be downloaded with a simple get request,
# feel free to create your own or extend the existing gist.
GENERIC_DOWNLOADER_GIST_URL = "https://gist.githubusercontent.com/AstralJaeger/7b620f40144ffaa6e2c48d56b0867594/raw/5055fb121c5c2e894f8412e613ee196106d61ee8/simple-downloader-regex.txt"


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

    def init(self, environment: dict[str, str], no_op: bool = False) -> None:
        """
            Initializes the downloader with an environment instance containing
            all environment variables from required env
            Params:
                environment (dict[str, str]): the environment dictionary
                no_op (bool): If the downloader should not actually write to disk
        """
        self.no_op = no_op
        self.environment = environment

    def get_supported_domains(self) -> list[Pattern]:
        """
            Returns a list of supported domains as compiled regex
            Params:
                None
            Returns:
                listOfRegex (list(Pattern)): A list of pattern.
        """
        return []

    def get_required_env(self) -> list[str]:
        """
            Returns a list of required environment variables
            Params:
                None
            Returns:
                listOfstr (list(str)): A list of str
        """
        return []

    async def download(self, url: str, target: str | PathLike) -> (str, Path):
        """
            Downloads a file from an url and saves it using save_to_disk
            Parameters:
                url (str): The url to download from
                target (str | PathLike): The path to the target folder, must exist before calling this method
            Returns:
                tuple (str, Path): A tuple containing file hash and the path as Path to the resulting file
        """
        pass

    def save_to_disk(self, response: Response, target: str | PathLike) -> (str, PathLike):
        """
            Saves a requests.Response to a file named as the hash of the file,
            determining the file type by using the mine-type or fleep.
            Parameters:
                response (Response): The requests.Response to save
                target (str | PathLike): The path to the target folder, must exist before calling this method
            Returns:
                tuple (str, PathLike): A tuple containing file hash and the path as Path to the resulting file
        """
        with SpooledTemporaryFile(512 * 1025 * 1024, "wb", dir = self.environment[envLbl.TEMP_LOCATION]) as tmp_file:
            shagen = sha256()
            for chunk in response.iter_content(chunk_size = 8192):
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
        """
            This method should be called to close open sessions and terminate them properly
        """
        pass


class SimpleDownloader(BaseDownloader):
    """
        A generic downloader that downloads any file, might not work in most cases
    """

    def __init__(self):
        super().__init__()

    def get_supported_domains(self) -> list[Pattern]:
        with requests.get(GENERIC_DOWNLOADER_GIST_URL) as response:
            response.raise_for_status()
            return [re.compile(entry) for entry in response.text.split(os.linesep)]

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

    async def download(self, url, target) -> (str, Path):
        try:
            content_id = self._parse_content_id(url)
        except IndexError:
            return f"{Fore.YELLOW}Could not parse: {url}{Fore.RESET}"

        headers = {
            "Authorization": f"Bearer {self.__auth['token']}",
            "Accept":        "application/json"
            }
        with self.__session.get(f"https://api.redgifs.com/v2/gifs/{content_id}", headers = headers) as response:
            response.raise_for_status()
            data = response.json()  # Consider to persist data json somewhere
            with self.__session.get(data["gif"]["urls"]["hd"], headers = headers, stream = True) as video_response:
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
            "Authorization": f"Client-ID {environment[envLbl.IMGUR_CLIENT_ID]} "
            }

    def get_supported_domains(self) -> list[Pattern]:
        # urls are i.imgur.com or sometimes l.imgur.com
        return [re.compile(r"([il]\.)?imgur\.com")]

    def get_required_env(self) -> list[str]:
        return [envLbl.IMGUR_CLIENT_ID]

    async def download(self, url, target) -> (str, Path):
        content_id = self._parse_content_id(url)
        with self.__session.get(f"https://api.imgur.com/3/image/{content_id}", headers = self.__auth,
                                stream = True) as data_response:
            data_response.raise_for_status()
            data = data_response.json()["data"]
            content_link = data["link"]
            if hasattr(data, "in_gallery") and data["in_gallery"]:
                print(f"{' ' * 18} URL: {url} is in gallery: {data['in_gallery']}")
            with self.__session.get(content_link, headers = self.__auth, stream = True) as content_response:
                return self.save_to_disk(content_response, target)

    def _parse_content_id(self, url: str) -> str:
        """
            Private mehtod
            Parses the content ID from an imgur url
            Params:
                url (str): The url to parse
            Returns:
                content_id (str): The content ID
        """
        if url.startswith("i"):
            # Redo this branch
            # last_slash_pos = url.rfind("/") + 1
            # dot_pos = url.rfind(".") if "." in url[last_slash_pos:] else len(url)
            # filename = url[last_slash_pos: dot_pos]
            return ""
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
        A downloader that provides support for imgur.com
    """

    def __init__(self):
        super().__init__()
        self.__session = requests.Session()
        self.__auth_token = ""
        self.__expires_in = ""
        self.__token_type = "bearer"
        self.__auth_created = None
        self.__keys = ["mp4", "webm", "largeGif", "mobile"]

    def init(self, environment: dict[str, str], no_op: bool = False) -> None:
        super().init(environment, no_op)

    def get_supported_domains(self) -> list[Pattern]:
        # urls are i.imgur.com or sometimes l.imgur.com
        return [re.compile(r"^gfycat\.com")]

    def get_required_env(self) -> list[str]:
        return [envLbl.GFYCAT_CLIENT_ID, envLbl.GFYCAT_CLIENT_SECRET]

    async def _authenticate(self):
        if self.__auth_created is None:
            # Initial authentication
            payload = {
                "grant_type":    "client_credentials",
                "client_id":     self.environment[envLbl.GFYCAT_CLIENT_ID],
                "client_secret": self.environment[envLbl.GFYCAT_CLIENT_SECRET]
                }
        else:
            # Re-authentication
            payload = {
                "grant_type":    "refresh",
                "client_id":     self.environment[envLbl.GFYCAT_CLIENT_ID],
                "client_secret": self.environment[envLbl.GFYCAT_CLIENT_SECRET],
                "refresh_token": self.__auth_token
                }

        if self.__auth_created is None or (datetime.datetime.now() - self.__auth_created).seconds >= self.__expires_in - 10:
            with self.__session.post(f"https://api.gfycat.com/v1/oauth/token", json = payload) as response:
                response.raise_for_status()
                response_data = response.json()
                self.__auth_token = response_data["access_token"]
                self.__expires_in = int(response_data["expires_in"])
                self.__token_type = response_data["token_type"]
                self.__auth_created = datetime.datetime.now()

    async def download(self, url, target) -> (str, Path):
        content_id = await self._parse_content_id(url)
        await self._authenticate()
        headers = {
            "Authorization": f"{self.__token_type} {self.__auth_token}"
            }
        with self.__session.get(f"https://api.gfycat.com/v1/gfycats/{content_id}", headers = headers,
                                stream = True) as data_response:
            data_response.raise_for_status()
            content = data_response.json()

            content_urls = dict(content["gfyItem"]["content_urls"])
            url = self._get_download_url(content_urls)
            with self.__session.get(url, headers = headers) as content_response:
                return self.save_to_disk(content_response, target)

    async def _parse_content_id(self, url: str) -> str:
        """
            Priave mehtod
            Parses the content ID from an imgur url
            Params:
                url (str): The url to parse
            Returns:
                content_id (str): The content ID
        """
        last_slash_pos = url.rfind("/") + 1
        first_minus_pos = last_slash_pos + url[last_slash_pos:].find("-") if "-" in url else len(url)
        return url[last_slash_pos: first_minus_pos]

    def _get_download_url(self, content_urls):
        for key in self.__keys:
            if key in content_urls:
                return content_urls[key]["url"]

    def close(self) -> None:
        self.__session.close()

