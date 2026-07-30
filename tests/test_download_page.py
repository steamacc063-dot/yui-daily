"""Contract tests for the deliberately minimal GitHub Pages download site."""

from __future__ import annotations

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parents[1]
PAGE = ROOT / "docs" / "index.html"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
VERSION = PROJECT["version"]
WHEEL_NAME = f"yui_daily-{VERSION}-py3-none-any.whl"
CHECKSUM_MANIFEST = ROOT / "checksums" / f"v{VERSION}.sha256"
RELEASE_DOWNLOAD = (
    f"https://github.com/steamacc063-dot/yui-daily/releases/download/v{VERSION}/"
    f"{WHEEL_NAME}"
)


class PageAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.links: list[dict[str, str]] = []
        self.meta: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        self.tags.append(tag)
        if tag == "a":
            self.links.append(values)
        if tag == "meta":
            self.meta.append(values)


def read_page() -> tuple[str, PageAudit]:
    html = PAGE.read_text("utf-8")
    audit = PageAudit()
    audit.feed(html)
    return html, audit


def test_download_page_is_small_semantic_and_dependency_free() -> None:
    html, audit = read_page()

    assert len(html.encode("utf-8")) < 20_000
    assert audit.tags.count("main") == 1
    assert audit.tags.count("h1") == 1
    assert "script" not in audit.tags
    assert not any(link.get("rel") == "stylesheet" for link in audit.links)
    assert any(meta.get("name") == "viewport" for meta in audit.meta)


def test_primary_download_points_to_the_immutable_versioned_release_asset() -> None:
    _, audit = read_page()

    download_links = [link for link in audit.links if link.get("data-download") == "primary"]

    assert len(download_links) == 1
    assert download_links[0]["href"] == RELEASE_DOWNLOAD
    assert download_links[0].get("aria-label") == f"Download Yui Daily {VERSION}"


def test_page_states_runtime_requirement_and_links_to_source() -> None:
    html, audit = read_page()
    checksum, filename = CHECKSUM_MANIFEST.read_text("utf-8").split()

    assert "Python 3.11+" in html
    assert f"python3 -m pip install ~/Downloads/{WHEEL_NAME}" in html
    assert re.fullmatch(r"[0-9a-f]{64}", checksum)
    assert filename == WHEEL_NAME
    assert f"SHA-256 {checksum}" in html
    assert any(
        link.get("href") == "https://github.com/steamacc063-dot/yui-daily"
        for link in audit.links
    )


def test_github_workflows_pin_actions_and_publish_release_assets() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")

    action_uses = re.findall(r"uses:\s*[^\s@]+@([^\s#]+)", ci + release)
    assert action_uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in action_uses)
    assert "tags:" in release
    assert "v*" in release
    assert "SOURCE_DATE_EPOCH" in release
    assert "sha256sum -c" in release
    assert "gh release create" in release
