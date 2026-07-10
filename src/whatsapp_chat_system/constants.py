"""Project defaults for the WhatsApp chat system."""

import os
from pathlib import Path


def _default_hermes_home() -> Path:
    raw = os.getenv('HERMES_HOME')
    if raw:
        return Path(raw).expanduser()
    return Path.home() / '.hermes'


DEFAULT_PROFILE = _default_hermes_home() / 'profiles' / 'whatsapp-support'
DEFAULT_ADMIN_IDS = {
    "8618011189006",
    "18011189006",
    "80226449133656@lid",
}
DEFAULT_ADMIN_TARGET = "whatsapp:80226449133656@lid"
DEFAULT_HOME = DEFAULT_PROFILE
