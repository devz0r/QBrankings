"""Download and cache nflverse data (https://github.com/nflverse/nflverse-data)."""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.request

import pandas as pd

from .formula import PBP_COLUMNS

RELEASES = 'https://github.com/nflverse/nflverse-data/releases/download'
PBP_URL = RELEASES + '/pbp/play_by_play_{season}.csv.gz'
ROSTER_URL = RELEASES + '/rosters/roster_{season}.csv'
ROSTER_COLUMNS = ['season', 'team', 'position', 'full_name', 'gsis_id', 'jersey_number', 'birth_date', 'draft_number', 'rookie_year', 'entry_year']


def _download(url: str, dest: str, max_age_hours: float) -> str:
    if os.path.exists(dest) and (time.time() - os.path.getmtime(dest)) < max_age_hours * 3600:
        return dest
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    tmp = f'{dest}.{os.getpid()}.part'
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, 'wb') as fh:
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
            os.replace(tmp, dest)
            return dest
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise FileNotFoundError(url) from err
            if attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f'could not download {url}')


def load_pbp(season: int, cache_dir: str = '.cache', max_age_hours: float = 6) -> pd.DataFrame:
    path = _download(PBP_URL.format(season=season), os.path.join(cache_dir, f'pbp_{season}.csv.gz'), max_age_hours)
    return pd.read_csv(path, low_memory=False, usecols=lambda c: c in PBP_COLUMNS)


def load_roster(season: int, cache_dir: str = '.cache', max_age_hours: float = 24) -> pd.DataFrame:
    path = _download(ROSTER_URL.format(season=season), os.path.join(cache_dir, f'roster_{season}.csv'), max_age_hours)
    return pd.read_csv(path, low_memory=False, usecols=lambda c: c in ROSTER_COLUMNS)
