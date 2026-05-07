"""Install Playwright browser binaries.

Usage:
    uv run install-browsers
"""

import subprocess
import sys


def main() -> None:
    print("Installing Playwright browser binaries...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chrome"],
        check=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
