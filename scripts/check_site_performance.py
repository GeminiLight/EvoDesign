"""Guard the static site's first-load resource budget without browser dependencies."""

import gzip
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1] / "docs"


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images = []
        self.scripts = []
        self.fonts = []
        self.styles = []
        self.in_style = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = dict(attrs)
        if tag == "link":
            assert attributes.get("rel") != "stylesheet", "Keep render styles in the generated inline bundle"
            if attributes.get("as") == "font":
                self.fonts.append(attributes["href"])
        if tag == "img" and attributes.get("src"):
            self.images.append(attributes)
        if tag == "script" and attributes.get("src"):
            self.scripts.append(attributes["src"])
            assert "defer" in attributes, "Page scripts must not block parsing"
        if tag == "style":
            self.in_style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.styles.append(data)


def asset(url: str) -> Path:
    parsed = urlsplit(url)
    assert not parsed.scheme and not parsed.netloc, f"Unexpected external rendering dependency: {url}"
    assert not parsed.path.startswith("/") and ".." not in Path(parsed.path).parts, url
    path = ROOT / parsed.path
    assert path.is_file(), f"Missing rendering resource: {url}"
    return path


def main() -> None:
    html = (ROOT / "index.html").read_bytes()
    page = Page()
    page.feed(html.decode())
    css = "".join(page.styles)
    assert css and len(css.encode()) < 90_000, "Inline CSS budget exceeded"
    assert len(gzip.compress(html)) < 40_000, "Compressed document budget exceeded"
    assert "@import" not in css, "CSS imports add another render dependency"
    for url in re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", css):
        if not url.startswith("data:"):
            asset(url)
    assert len(page.fonts) == 2
    assert sum(asset(url).stat().st_size for url in page.fonts) < 70_000
    assert sum(asset(url).stat().st_size for url in page.scripts) < 50_000
    eager_bytes = 0
    for image in page.images:
        assert image.get("width") and image.get("height"), "Reserve image dimensions to avoid layout shifts"
        sources = [image["src"]] + [part.strip().split()[0] for part in image.get("srcset", "").split(",") if part.strip()]
        paths = [asset(url) for url in sources]
        if image.get("loading") != "lazy":
            eager_bytes += max(path.stat().st_size for path in paths)
        if image.get("fetchpriority") == "high":
            assert image.get("srcset") and image.get("sizes"), "The hero needs responsive previews"
            assert max(path.stat().st_size for path in paths) < 40_000
        elif "/previews/" in image["src"]:
            assert image.get("loading") == "lazy", "Paper figures must not compete with the hero"
            assert max(path.stat().st_size for path in paths) < 350_000
    assert eager_bytes < 50_000, "Initial image transfer budget exceeded"
    print("Verified same-origin rendering resources, inline CSS, responsive previews and first-load byte budgets.")


if __name__ == "__main__":
    main()
