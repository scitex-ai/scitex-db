"""Regression test: importing tests/conftest.py must not touch site-packages."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"


def test_conftest_leaves_site_packages_untouched():
    # Arrange
    child_code = (
        "import os, runpy, site\n"
        "os.environ['COVERAGE_PROCESS_START'] = 'SENTINEL_PROCESS_START'\n"
        "os.environ['COVERAGE_FILE'] = 'SENTINEL_COVERAGE_FILE'\n"
        "dirs = []\n"
        "try:\n"
        "    dirs += list(site.getsitepackages())\n"
        "except Exception:\n"
        "    pass\n"
        "try:\n"
        "    dirs.append(site.getusersitepackages())\n"
        "except Exception:\n"
        "    pass\n"
        "before = {}\n"
        "for d in dirs:\n"
        "    try:\n"
        "        before[d] = sorted(os.listdir(d))\n"
        "    except OSError:\n"
        "        before[d] = None\n"
        f"runpy.run_path({str(CONFTEST_PATH)!r})\n"
        "after = {}\n"
        "for d in dirs:\n"
        "    try:\n"
        "        after[d] = sorted(os.listdir(d))\n"
        "    except OSError:\n"
        "        after[d] = None\n"
        "assert before == after, 'conftest.py modified a site-packages directory'\n"
        "assert os.environ.get('COVERAGE_PROCESS_START') == 'SENTINEL_PROCESS_START'\n"
        "assert os.environ.get('COVERAGE_FILE') == 'SENTINEL_COVERAGE_FILE'\n"
    )
    # Act
    proc = subprocess.run(
        [sys.executable, "-c", child_code],
        capture_output=True,
        text=True,
    )
    # Assert
    assert proc.returncode == 0, (
        f"child interpreter failed (exit {proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
