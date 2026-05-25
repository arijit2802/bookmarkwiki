"""
Import Safari bookmarks into the DKE API.

Usage:
    python import_safari_bookmarks.py [--api-url http://localhost:8000]
    python import_safari_bookmarks.py --folder "AI Research"
    python import_safari_bookmarks.py --list-folders

Requires Full Disk Access for the terminal in:
    System Settings > Privacy & Security > Full Disk Access
"""

import argparse
import json
import plistlib
import urllib.request
import urllib.error
from pathlib import Path


def extract_urls(node, urls=None):
    if urls is None:
        urls = []
    if not isinstance(node, dict):
        return urls
    if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
        url = node.get("URLString", "")
        if url.startswith("http"):
            urls.append(url)
    for child in node.get("Children", []):
        extract_urls(child, urls)
    return urls


def find_folder(node, folder_name):
    """Return the subtree node whose Title matches folder_name (case-insensitive)."""
    if not isinstance(node, dict):
        return None
    if (
        node.get("WebBookmarkType") == "WebBookmarkTypeList"
        and node.get("Title", "").lower() == folder_name.lower()
    ):
        return node
    for child in node.get("Children", []):
        result = find_folder(child, folder_name)
        if result:
            return result
    return None


def list_folders(node, folders=None, depth=0):
    """Collect all folder names from the bookmark tree."""
    if folders is None:
        folders = []
    if not isinstance(node, dict):
        return folders
    if node.get("WebBookmarkType") == "WebBookmarkTypeList":
        title = node.get("Title", "")
        if title and title not in ("BookmarksBar", "BookmarksMenu", "com.apple.ReadingList"):
            folders.append("  " * depth + title)
    for child in node.get("Children", []):
        list_folders(child, folders, depth + 1)
    return folders


def load_safari_bookmarks():
    plist_path = Path.home() / "Library/Safari/Bookmarks.plist"
    if not plist_path.exists():
        raise FileNotFoundError(f"Safari bookmarks not found at {plist_path}")
    with open(plist_path, "rb") as f:
        return plistlib.load(f)


def post_to_api(urls, api_url):
    payload = json.dumps({"urls": urls}).encode()
    req = urllib.request.Request(
        f"{api_url}/bookmarks/bulk",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(description="Import Safari bookmarks into DKE")
    parser.add_argument("--api-url", default="http://localhost:8000", help="DKE API base URL")
    parser.add_argument("--dry-run", action="store_true", help="Print URLs without sending to API")
    parser.add_argument("--folder", help="Only import bookmarks from this folder name")
    parser.add_argument("--list-folders", action="store_true", help="List all available folder names and exit")
    args = parser.parse_args()

    print("Reading Safari bookmarks...")
    try:
        data = load_safari_bookmarks()
    except PermissionError:
        print("ERROR: Permission denied.")
        print("Grant Full Disk Access to Terminal in:")
        print("  System Settings > Privacy & Security > Full Disk Access")
        return
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return

    if args.list_folders:
        folders = list_folders(data)
        print("Available folders:")
        for f in folders:
            print(f"  {f}")
        return

    if args.folder:
        node = find_folder(data, args.folder)
        if not node:
            print(f"ERROR: Folder '{args.folder}' not found.")
            print("Run with --list-folders to see available folders.")
            return
        urls = extract_urls(node)
        print(f"Found {len(urls)} bookmarks in folder '{args.folder}'")
    else:
        urls = extract_urls(data)
        print(f"Found {len(urls)} bookmarks")

    if args.dry_run:
        for url in urls:
            print(url)
        return

    print(f"Sending to {args.api_url}/bookmarks/bulk ...")
    try:
        result = post_to_api(urls, args.api_url)
        print(f"Queued {result.get('queued', '?')} bookmarks for processing")
    except urllib.error.URLError as e:
        print(f"ERROR: Could not reach API at {args.api_url}")
        print(f"  Make sure the DKE backend is running (uvicorn backend.api.main:app)")
        print(f"  Details: {e}")


if __name__ == "__main__":
    main()
