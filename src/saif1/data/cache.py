"""FastF1 on-disk cache configuration.

FastF1 requires an explicit cache directory to avoid re-downloading timing
data on every run. This module centralizes that setup so it only needs to
be called once per process.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fastf1

from saif1.config import DEFAULT_CACHE_DIR

logger = logging.getLogger(__name__)

_cache_enabled = False


def enable_cache(cache_dir: Path | str = DEFAULT_CACHE_DIR) -> None:
    """Enable FastF1's on-disk cache, creating the directory if needed.

    Idempotent: safe to call multiple times (e.g. once per script and
    once per test) without side effects beyond the first call.
    """
    global _cache_enabled
    if _cache_enabled:
        return

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_path))
    _cache_enabled = True
    logger.info("FastF1 cache enabled at %s", cache_path)
