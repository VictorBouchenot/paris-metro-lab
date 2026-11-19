"""Download and extract the IDFM GTFS feed.

Source: Ile-de-France Mobilities open data, mirrored by OpenDataSoft.
The feed is refreshed regularly; re-run to get current timetables.
"""
from __future__ import annotations

import urllib.request
import zipfile
from pathlib import Path

GTFS_URL = "https://eu.ftp.opendatasoft.com/stif/GTFS/IDFM-gtfs.zip"


def download_gtfs(data_dir: Path, url: str = GTFS_URL) -> Path:
    """Fetch the GTFS zip into data_dir and extract it to data_dir/gtfs."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / "gtfs.zip"
    print(f"Downloading {url} -> {zip_path}")
    urllib.request.urlretrieve(url, zip_path)
    out = data_dir / "gtfs"
    out.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    print(f"Extracted {len(list(out.glob('*.txt')))} files to {out}")
    return out
