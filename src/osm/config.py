"""Settings, paths, and constants."""

from __future__ import annotations

from pathlib import Path

# Pipeline outputs anchor to the project root (this file's grandparent).
try:
    _PKG_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = _PKG_DIR.parent.parent
except NameError:
    PROJECT_ROOT = Path.cwd()

# User-level config directory
CONFIG_DIR = Path.home() / ".config" / "osm"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"
HISTORY_CACHE_DIR = CONFIG_DIR / "history_cache"

# Overpass API endpoints
OVERPASS_PRIMARY = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRROR = "https://overpass.kumi.systems/api/interpreter"

OVERPASS_HEADERS = {
    "User-Agent": "osm-audit-pipeline/0.1 (Hamilton County TIGER defect audit)",
    "Accept": "application/json",
}

# OSM API
OSM_API_BASE = "https://api.openstreetmap.org/api/0.6"
OSM_AUTH_URL = "https://www.openstreetmap.org/oauth2/authorize"
OSM_TOKEN_URL = "https://www.openstreetmap.org/oauth2/token"
OAUTH_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

# Defect classification
CRITICAL = "CRITICAL"
HIGH = "HIGH"
LOW = "LOW"

CLASS_AB = "AB"
CLASS_A = "A"
CLASS_B = "B"
CLASS_C = "C"
CLASS_ORDER = [CLASS_AB, CLASS_A, CLASS_B, CLASS_C]

# Gap detection thresholds (metres)
GAP_THRESHOLD_M = 30.0
GAP_CLUSTER_M = 5.0

# Cache management
CACHE_RETENTION_DAYS = 14
CACHE_KEEP_NEWEST = 3

# Sanity threshold — warn if Overpass returns fewer elements than this
SANITY_THRESHOLD = 100


def ensure_config_dirs() -> None:
    """Create config directories if they don't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
