from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import json
import re
from urllib.request import Request, urlopen
from xml.etree import ElementTree


_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/shenggaoli953-pixel/"
    "fanqie-publisher-assistant/releases/latest"
)
_RELEASES_URL = (
    "https://github.com/shenggaoli953-pixel/"
    "fanqie-publisher-assistant/releases"
)
_RELEASE_FEED_URL = f"{_RELEASES_URL}.atom"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:$|[\s:：—-].*)")
_ATOM_NAMESPACE = "{http://www.w3.org/2005/Atom}"


class UpdateStatus(StrEnum):
    CURRENT = "current"
    AVAILABLE = "available"


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateReport:
    status: UpdateStatus
    current_version: str
    latest_version: str
    release_url: str


def check_for_update(
    current_version: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> UpdateReport:
    current = _parse_version(current_version)
    try:
        payload = _read_latest_release(opener)
    except OSError:
        latest, release_url = _read_release_feed(opener)
    else:
        if not isinstance(payload, dict):
            raise UpdateCheckError("更新服务返回的数据无效")
        latest = _parse_version(str(payload.get("tag_name", "")))
        release_url = str(payload.get("html_url") or _RELEASES_URL)

    return UpdateReport(
        status=(UpdateStatus.AVAILABLE if latest > current else UpdateStatus.CURRENT),
        current_version=_format_version(current),
        latest_version=_format_version(latest),
        release_url=release_url,
    )


def _read_latest_release(opener: Callable[..., object]) -> object:
    request = Request(
        _LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FanqiePublisher",
        },
    )
    try:
        with opener(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except OSError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateCheckError("更新服务返回的数据无效") from error


def _read_release_feed(
    opener: Callable[..., object],
) -> tuple[tuple[int, int, int], str]:
    request = Request(_RELEASE_FEED_URL, headers={"User-Agent": "FanqiePublisher"})
    try:
        with opener(request, timeout=8) as response:
            feed = ElementTree.fromstring(response.read())
    except (OSError, ElementTree.ParseError) as error:
        raise UpdateCheckError("暂时无法连接更新服务，请稍后重试") from error
    entry = feed.find(f"{_ATOM_NAMESPACE}entry")
    if entry is None:
        raise UpdateCheckError("更新服务没有可用的稳定版本")
    latest = _parse_version(entry.findtext(f"{_ATOM_NAMESPACE}title") or "")
    release_url = next(
        (
            str(link.get("href"))
            for link in entry.findall(f"{_ATOM_NAMESPACE}link")
            if link.get("rel") in {None, "alternate"} and link.get("href")
        ),
        _RELEASES_URL,
    )
    return latest, release_url


def _parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        raise UpdateCheckError("更新服务返回的版本号无效")
    return tuple(int(part) for part in match.groups())


def _format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)
