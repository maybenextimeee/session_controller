"""Тесты проверки обновлений — без настоящего интернета."""

import io
import json

from session_controller import updates
from session_controller.updates import Release, is_newer, parse_release, parse_version


def test_parse_version():
    assert parse_version("v0.7.0") == (0, 7, 0)
    assert parse_version("1.2") == (1, 2)
    assert parse_version(" V2.0.1 ") == (2, 0, 1)
    assert parse_version("beta") is None
    assert parse_version("") is None


def test_is_newer():
    assert is_newer("0.7.0", "0.6.0")
    assert is_newer("1.0.0", "0.9.9")
    assert is_newer("0.10.0", "0.9.0")  # не по алфавиту, а по числам
    assert not is_newer("0.6.0", "0.6.0")
    assert not is_newer("0.6", "0.6.0")
    assert not is_newer("0.5.0", "0.6.0")
    assert not is_newer("мусор", "0.6.0")


def test_parse_release():
    good = {"tag_name": "v0.7.0", "html_url": "https://github.com/x/releases/tag/v0.7.0"}
    assert parse_release(good) == Release("0.7.0", good["html_url"])
    assert parse_release({**good, "draft": True}) is None
    assert parse_release({**good, "prerelease": True}) is None
    assert parse_release({**good, "tag_name": "nightly"}) is None
    assert parse_release({"tag_name": "v1.0.0"}) is None
    assert parse_release(["не", "словарь"]) is None


def test_fetches_github_latest(monkeypatch):
    answer = {"tag_name": "v0.7.1", "html_url": "https://example/v0.7.1"}

    def github(request, timeout):
        assert request.full_url.endswith("/releases/latest")
        return io.BytesIO(json.dumps(answer).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", github)
    assert updates.fetch_latest() == Release("0.7.1", answer["html_url"])


def test_no_internet_is_quiet(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("сети нет")

    monkeypatch.setattr(updates.urllib.request, "urlopen", fail)
    assert updates.fetch_latest() is None
