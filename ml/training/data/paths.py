"""
MIMIC-IV data path resolution (environment-driven, machine-agnostic).

The training config (ml/training/config/config.py) hardcodes a relative
`MIMIC_BASE` reflecting the research-workspace layout. On the AWS training box
the data lives at /home/ubuntu/mimic_data. Rather than bake either path into the
pipeline, this module resolves the root from the environment so the SAME code
runs unchanged on a laptop (tiny synthetic sample), the AWS box, or CI.

Resolution order for the MIMIC-IV root:
    1. Explicit argument to `resolve_mimic_root`
    2. PRESCP_MIMIC_ROOT environment variable
    3. config.MIMIC_BASE (last-resort default, likely only valid in research WS)
"""

from __future__ import annotations

import os
from pathlib import Path

from ml.training.config import config

# Environment variable pointing at the MIMIC-IV 3.1 root that contains the
# `hosp/` and `icu/` subdirectories.
MIMIC_ROOT_ENV: str = "PRESCP_MIMIC_ROOT"

# Standard MIMIC-IV module subdirectories.
HOSP_DIRNAME: str = "hosp"
ICU_DIRNAME: str = "icu"


def resolve_mimic_root(explicit: str | Path | None = None) -> Path:
    """Resolve the MIMIC-IV data root.

    Args:
        explicit: Caller-provided root; wins over the environment and default.

    Returns:
        Path to the directory containing `hosp/` and `icu/`. The path is NOT
        required to exist here — existence is validated by `hosp_dir`/`icu_dir`
        at the point of use, so callers get a precise error naming the missing
        subdirectory.
    """
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(MIMIC_ROOT_ENV)
    if env_value:
        return Path(env_value)
    return Path(config.MIMIC_BASE)


def hosp_dir(root: str | Path | None = None) -> Path:
    """Return the `hosp/` module directory under the resolved MIMIC root.

    Raises:
        FileNotFoundError: If the directory does not exist, with a clear message
            pointing at the resolved location (aids AWS-vs-local misconfig).
    """
    path = resolve_mimic_root(root) / HOSP_DIRNAME
    if not path.exists():
        raise FileNotFoundError(
            f"MIMIC-IV hosp/ directory not found at {path}. "
            f"Set {MIMIC_ROOT_ENV} to the dataset root."
        )
    return path


def icu_dir(root: str | Path | None = None) -> Path:
    """Return the `icu/` module directory under the resolved MIMIC root.

    Raises:
        FileNotFoundError: If the directory does not exist, naming the location.
    """
    path = resolve_mimic_root(root) / ICU_DIRNAME
    if not path.exists():
        raise FileNotFoundError(
            f"MIMIC-IV icu/ directory not found at {path}. "
            f"Set {MIMIC_ROOT_ENV} to the dataset root."
        )
    return path
