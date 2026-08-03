"""Environment loading shared by the CLI and the Streamlit app.

Both entry points read configuration from a local ``.env``. The Streamlit app has
to do so at import time, because Streamlit executes the page module top to bottom
— there is no ``main()`` to hide the side effect in. That makes importing the app
mutate ``os.environ`` for the whole process, which silently breaks test isolation:
a developer with a working ``.env`` sees failures CI never reproduces.

:data:`SKIP_DOTENV_ENV_VAR` is the opt-out. The test suite sets it, and so can any
deployment that injects real environment variables and wants no ``.env`` involved.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

#: Set to any non-empty value to stop the entry points reading a local .env.
SKIP_DOTENV_ENV_VAR = "GRANT_ASSISTANT_SKIP_DOTENV"


def load_environment(dotenv_path: str | Path | None = None) -> bool:
    """Load ``.env`` into the environment unless the opt-out is set.

    Returns True when a file was loaded. Existing environment variables always
    win — ``python-dotenv`` does not override them — so a container's injected
    configuration is never clobbered by a stray file in the image.
    """
    if os.environ.get(SKIP_DOTENV_ENV_VAR, "").strip():
        logger.debug("%s is set — skipping .env", SKIP_DOTENV_ENV_VAR)
        return False
    if dotenv_path is not None:
        return load_dotenv(dotenv_path=dotenv_path)
    return load_dotenv()
