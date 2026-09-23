#!/usr/bin/env python3
"""Create a private SQLite-consistent backup plus course attachments."""
import argparse
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone


def backup(database: Path, media: Path, destination: Path) -> Path:
    if not database.is_file():
        raise FileNotFoundError(f"Database does not exist: {database}")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = destination / f"course-square-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="course-square-backup-") as temporary:
        snapshot = Path(temporary) / "db.sqlite3"
        with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Database integrity check failed")
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as raw:
                with tarfile.open(fileobj=raw, mode="w:gz") as archive:
                    archive.add(snapshot, arcname="db.sqlite3")
                    if media.is_dir():
                        archive.add(media, arcname="media")
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/var/lib/course-square/db.sqlite3"))
    parser.add_argument("--media", type=Path, default=Path("/var/lib/course-square/media"))
    parser.add_argument("--destination", type=Path, default=Path("/var/backups/course-square"))
    args = parser.parse_args()
    print(backup(args.database, args.media, args.destination))
