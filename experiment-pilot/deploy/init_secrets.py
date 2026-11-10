"""Initialize Compose secret files without replacing existing credentials."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
from pathlib import Path

NAMES = ("db_password", "analyst_token", "reviewer_token")


def initialize(directory: Path) -> int:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
        raise ValueError("Secret directory must be a real directory with mode 0700")
    created = 0
    for name in NAMES:
        path = directory / name
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not stat.S_ISREG(path.lstat().st_mode) or not path.read_text().strip():
                raise ValueError(f"Invalid secret file: {path}")
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(secrets.token_urlsafe(36) + "\n")
            file.flush()
            # Compose file secrets are bind-mounted. The private parent protects the host copy.
            os.fchmod(file.fileno(), 0o444)
        created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path(".secrets"))
    args = parser.parse_args()
    print(f"Initialized {initialize(args.directory)} new secret files in {args.directory}")


if __name__ == "__main__":
    main()
