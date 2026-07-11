"""Constants for the GL.iNet integration."""

from datetime import timedelta

DOMAIN = "glinet4"
SCAN_INTERVAL = timedelta(seconds=30)
DATA_GLINET = "glinet"
API_PATH = "/rpc"
GLINET_FRIENDLY_NAME = "GL.iNet"
GLINET_DEFAULT_URL = "http://192.168.8.1"
GLINET_DEFAULT_PW = "goodlife"
GLINET_DEFAULT_USERNAME = "root"

CONF_TITLE = "title"

# Repair-issue translation key; the per-entry issue id is
# f"{ISSUE_STATISTICS_NOT_COLLECTING}_{entry_id}".
ISSUE_STATISTICS_NOT_COLLECTING = "statistics_not_collecting"
ISSUE_TAILSCALE_REAUTH = "tailscale_reauth_required"
ISSUE_ROUTER_MODE = "router_mode"
