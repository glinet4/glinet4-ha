"""Constants for the GL.iNet integration."""

from datetime import timedelta

DOMAIN = "glinet4"

# Polling is split across four coordinators, bucketed by how fast the
# underlying data actually changes (measured against a live MT6000 over a 6h
# window, ~635 polls):
#
#   wan_speed          636/635 changes (100%)  -> FAST
#   connected clients  presence, latency-sensitive -> TRACKER
#   system status      cpu/mem/load, 19-99%    -> SCAN (main)
#   tailscale/led/     1 change in 6 hours     -> SLOW
#   flow stats/mode
#
# FAST is 10s because the router recomputes its WAN rate every ~3s (verified by
# 1s sampling: 58 of 61 runs were exactly 3 identical samples). Polling slower
# than that aliases - at the old 30s interval only ~9% of traffic was sampled.
# Below 3s buys nothing; 10s keeps us above HA's documented 5s floor while
# giving long-term statistics ~30 samples per 5-minute bucket instead of ~9.
FAST_SCAN_INTERVAL = timedelta(seconds=10)
TRACKER_SCAN_INTERVAL = timedelta(seconds=30)
SCAN_INTERVAL = timedelta(seconds=60)
SLOW_SCAN_INTERVAL = timedelta(minutes=5)
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
