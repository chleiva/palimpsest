#!/usr/bin/env python3
"""Download the v1.0 deposit package from Zenodo, verify its SHA-256, and unpack the cached data
(frozen streams, extracted claims, raw model outputs, Wikidata revisions) into this checkout, so that
every table and figure can be regenerated without an API call.

Usage: python scripts/fetch_release_data.py [--url URL] [--keep-zip]
"""
import hashlib, io, os, sys, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://zenodo.org/records/23127764/files/palimpsest-v1.0.zip?download=1"
SHA256 = "686cf0bbf43f2cf7177aa84abaf5e27397b9543ae5363854545b26bcbf077dc6"
PREFIX = "palimpsest-v1.0/"
TAKE = ("data/", "bridge/")           # only the cached data; code and paper come from git


def main():
    a = sys.argv[1:]
    url = a[a.index("--url") + 1] if "--url" in a else URL
    print(f"downloading {url} ...", flush=True)
    with urllib.request.urlopen(url, timeout=600) as r:
        blob = r.read()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != SHA256:
        sys.exit(f"SHA-256 mismatch: got {digest}, expected {SHA256}; refusing to unpack")
    print(f"ok: {len(blob)/1e6:.1f} MB, SHA-256 verified", flush=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith(PREFIX):
                continue
            rel = name[len(PREFIX):]
            if not rel.startswith(TAKE) or info.is_dir():
                continue
            dst = os.path.join(ROOT, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(info) as src, open(dst, "wb") as out:
                out.write(src.read())
            n += 1
    if "--keep-zip" in a:
        open(os.path.join(ROOT, "palimpsest-v1.0.zip"), "wb").write(blob)
    print(f"unpacked {n} files under data/ and bridge/. Next: python scripts/make_tables.py && python scripts/make_figures.py")


if __name__ == "__main__":
    main()
