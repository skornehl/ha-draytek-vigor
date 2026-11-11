"""Constants for DrayTek Vigor."""
from __future__ import annotations

DOMAIN = "draytek_vigor"
DEFAULT_HOST = "192.168.1.2"
DEFAULT_USERNAME = "admin"
# The modem answers HTTPS with its own self-signed certificate.
DEFAULT_SSL = True
DEFAULT_VERIFY_SSL = False
SCAN_INTERVAL_SECONDS = 60
LOGIN_REJECTIONS_BEFORE_REAUTH = 3
# Line status the modem reports once trained; anything else means no sync.
SYNC_STATUS = "SHOWTIME"
