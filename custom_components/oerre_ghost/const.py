"""Constants for Oerre Ghost."""

DOMAIN = "oerre_ghost"

CONF_LISTEN_PORT = "listen_port"
CONF_UPSTREAM_HOST = "upstream_host"
CONF_UPSTREAM_PORT = "upstream_port"
CONF_APP_PORT = "app_port"
CONF_KNOWN_MACS = "known_macs"

DEFAULT_LISTEN_PORT = 11000
DEFAULT_UPSTREAM_HOST = "app-oerre.it"  # resolved via public DNS
FALLBACK_CLOUD_IP = "62.97.61.164"  # app-oerre.it, Oct 2026
DEFAULT_UPSTREAM_PORT = 11000
DEFAULT_APP_PORT = 4521

SIGNAL_NEW_UNIT = f"{DOMAIN}_new_unit"
