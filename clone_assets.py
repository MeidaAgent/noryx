import argparse
import hashlib
import mimetypes
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


MEDIA_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".flac",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
    ".m3u8",
    ".ts",
}


def build_asset_filename(url, content_type="", used_names=None):
    parsed = urlparse(url)
    name = re.sub(
        r"[^A-Za-z0-9._-]", "_", unquote(os.path.basename(parsed.path)) or "asset"
    )
    stem, suffix = os.path.splitext(name)
    if not suffix:
        suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ""
    name = f"{stem or 'asset'}{suffix.lower()}"
    if used_names is not None and name in used_names and used_names[name] != url:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        name = f"{stem or 'asset'}_{digest}{suffix.lower()}"
    if used_names is not None:
        used_names[name] = url
    return name


def ultimate_clone(html_file, base_url, output_dir="sentro_clone", fetch_missing=True):
    output = Path(output_dir)
    dirs = {
        "css": output / "css",
        "js": output / "js",
        "img": output / "images",
        "font": output / "fonts",
        "media": output / "media",
        "misc": output / "assets",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
    html_path = Path(html_file)
    if not html_path.exists() and fetch_missing:
        try:
            response = session.get(base_url, timeout=(5, 15))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            print(f"[*] HTML utama diambil dari {base_url}")
        except requests.RequestException as exc:
            print(f"[-] Gagal mengambil HTML dari {base_url}: {exc}")
            return False
    else:
        try:
            soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
        except (OSError, UnicodeError) as exc:
            print(f"[-] Error membaca HTML: {exc}")
            return False
    downloaded = {}
    css_cache = {}
    used_names = {}

    def select_asset_directory(url, content_type=""):
        ext = Path(urlparse(url).path).suffix.lower()
        if ext == ".css" or "text/css" in content_type:
            return dirs["css"]
        if ext in {".js", ".mjs"} or "javascript" in content_type:
            return dirs["js"]
        if ext in {".woff", ".woff2", ".ttf", ".otf", ".eot"}:
            return dirs["font"]
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".avif", ".bmp"}:
            return dirs["img"]
        if ext in MEDIA_EXTENSIONS or content_type.startswith(("audio/", "video/")):
            return dirs["media"]
        return dirs["misc"]

    def download_asset(url, directory=None):
        if not url or url.startswith(("data:", "blob:", "#", "javascript:")):
            return url
        full_url = urljoin(base_url, url)
        if urlparse(full_url).scheme not in {"http", "https"}:
            return url
        if full_url in downloaded:
            return downloaded[full_url]
        try:
            response = session.get(full_url, timeout=(5, 15))
            response.raise_for_status()
            target_dir = directory or select_asset_directory(
                full_url, response.headers.get("content-type", "")
            )
            target = target_dir / build_asset_filename(
                full_url, response.headers.get("content-type", ""), used_names
            )
            target.write_bytes(response.content)
            relative = target.relative_to(output).as_posix()
            downloaded[full_url] = relative
            print(f"  [+] Didapat: {relative}")
            return relative
        except requests.RequestException as exc:
            print(f"  [-] Gagal download {full_url}: {exc}")
            downloaded[full_url] = url
            return url

    css_url_pattern = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
    import_pattern = re.compile(
        r"(@import\s+)(url\(\s*['\"]?)([^)'\"\s]+)(['\"]?\s*\))", re.IGNORECASE
    )

    def process_stylesheet(css_url):
        full_url = urljoin(base_url, css_url)
        if full_url in css_cache:
            return css_cache[full_url]
        local_path = download_asset(full_url, dirs["css"])
        if local_path == full_url or local_path == css_url:
            return css_url
        css_cache[full_url] = local_path
        try:
            response = session.get(full_url, timeout=(5, 15))
            response.raise_for_status()
            css_content = response.text

            def replace_import(match):
                imported = urljoin(full_url, match.group(3))
                imported_local = process_stylesheet(imported)
                return f"{match.group(1)}url('{Path(imported_local).name}')"

            css_content = import_pattern.sub(replace_import, css_content)

            def replace_url(match):
                asset = match.group(2).strip()
                if asset.startswith(("data:", "#")):
                    return match.group(0)
                asset_local = download_asset(urljoin(full_url, asset))
                if asset_local == asset:
                    return match.group(0)
                return f"url('../{Path(asset_local).parent.name}/{Path(asset_local).name}')"

            (output / local_path).write_text(
                css_url_pattern.sub(replace_url, css_content), encoding="utf-8"
            )
            return local_path
        except (OSError, requests.RequestException) as exc:
            print(f"  [-] Gagal proses CSS {full_url}: {exc}")
            return css_url

    for link in soup.find_all("link"):
        href = link.get("href")
        rel = {item.lower() for item in link.get("rel", [])}
        if not href:
            continue
        if "stylesheet" in rel:
            link["href"] = process_stylesheet(href)
        elif rel.intersection({"icon", "manifest", "preload", "modulepreload"}):
            link["href"] = download_asset(href)

    for script in soup.find_all("script", src=True):
        script["src"] = download_asset(script["src"], dirs["js"])

    def rewrite_css_fragment(value, source_url=base_url):
        def replace_url(match):
            asset = match.group(2).strip()
            if asset.startswith(("data:", "#")):
                return match.group(0)
            local = download_asset(urljoin(source_url, asset))
            return f"url('{local}')" if local != asset else match.group(0)

        return css_url_pattern.sub(replace_url, value)

    media_url_pattern = re.compile(
        r"""(["'])(https?://[^"']+\.(?:mp3|wav|ogg|m4a|flac|mp4|webm|mov|avi|mkv|m3u8|ts)(?:\?[^"']*)?|/[^"']+\.(?:mp3|wav|ogg|m4a|flac|mp4|webm|mov|avi|mkv|m3u8|ts)(?:\?[^"']*)?)\1""",
        re.IGNORECASE,
    )

    def rewrite_media_urls(value):
        def replace_media(match):
            original = match.group(2)
            local = download_asset(original)
            return f"{match.group(1)}{local}{match.group(1)}" if local != original else match.group(0)

        return media_url_pattern.sub(replace_media, value)

    for style in soup.find_all("style"):
        if style.string:
            style.string.replace_with(rewrite_css_fragment(style.string))
    for tag in soup.find_all(style=True):
        tag["style"] = rewrite_css_fragment(tag["style"])
    for script in soup.find_all("script"):
        if script.string:
            script.string.replace_with(rewrite_media_urls(script.string))

    url_attributes = {
        "img": ("src", "longdesc"),
        "source": ("src",),
        "video": ("src", "poster"),
        "audio": ("src",),
        "track": ("src",),
        "iframe": ("src",),
        "embed": ("src",),
        "object": ("data",),
    }
    for tag_name, attributes in url_attributes.items():
        for tag in soup.find_all(tag_name):
            for attribute in attributes:
                if tag.get(attribute):
                    tag[attribute] = download_asset(tag[attribute])
            if tag.get("srcset"):
                entries = []
                for item in tag["srcset"].split(","):
                    parts = item.strip().split()
                    if parts:
                        parts[0] = download_asset(parts[0])
                    entries.append(" ".join(parts))
                tag["srcset"] = ", ".join(entries)

    for tag in soup.find_all(["img", "source", "video", "audio"]):
        for attribute in ("data-src", "data-lazy-src", "data-original", "data-poster"):
            if tag.get(attribute):
                tag[attribute] = download_asset(tag[attribute])

    for meta in soup.find_all("meta", content=True):
        if meta.get("property", "").lower() in {"og:image", "og:video"} or meta.get(
            "name", ""
        ).lower() in {"twitter:image", "twitter:player:stream"}:
            meta["content"] = download_asset(meta["content"])

    for script in soup.find_all("script", src=True):
        local_script = script["src"]
        script_path = output / local_script
        if script_path.is_file():
            try:
                script_content = script_path.read_text(encoding="utf-8")
                script_path.write_text(rewrite_media_urls(script_content), encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                print(f"  [-] Gagal memproses media di {local_script}: {exc}")

    (output / "index.html").write_text(str(soup), encoding="utf-8")
    print(f"\n[OK] ULTIMATE CLONE SELESAI: {output.resolve()}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download HTML assets and rewrite them for offline use."
    )
    parser.add_argument(
        "html_file",
        nargs="?",
        default="sentro_trade_full.html",
        help="Path to the local HTML file (default: sentro_trade_full.html)",
    )
    parser.add_argument(
        "--base-url",
        default="https://sentro.trade",
        help="Website base URL used to resolve relative links",
    )
    parser.add_argument(
        "--output-dir",
        default="sentro_clone",
        help="Folder where the cloned site will be written",
    )
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Kept for compatibility; missing HTML is downloaded automatically",
    )
    args = parser.parse_args()
    sys.exit(
        0
        if ultimate_clone(
            args.html_file, args.base_url, args.output_dir, True
        )
        else 1
    )