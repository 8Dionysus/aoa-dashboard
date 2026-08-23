#!/usr/bin/env python3
"""Validate the owner-local source release surface without publishing it."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(RuntimeError):
    """Raised when a release surface is incomplete or inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def section(body: str, heading: str) -> str | None:
    match = re.search(rf"^### {re.escape(heading)}\s*$", body, re.MULTILINE)
    if match is None:
        return None
    tail = body[match.end() :]
    next_heading = re.search(r"^### ", tail, re.MULTILINE)
    end = next_heading.start() if next_heading else len(tail)
    value = tail[:end].strip()
    return value or None


def main() -> int:
    pyproject_path = ROOT / "pyproject.toml"
    changelog_path = ROOT / "CHANGELOG.md"
    readme_path = ROOT / "README.md"
    posture_path = ROOT / "docs" / "RELEASE_POSTURE.md"
    releasing_path = ROOT / "docs" / "RELEASING.md"
    reconciliation_path = ROOT / "docs" / "RELEASE_RECONCILIATION.md"

    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        changelog = changelog_path.read_text(encoding="utf-8")
        readme = readme_path.read_text(encoding="utf-8")
        posture = posture_path.read_text(encoding="utf-8")
        reconciliation = reconciliation_path.read_text(encoding="utf-8")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"cannot read release surface: {exc}") from exc

    version = pyproject.get("project", {}).get("version")
    require(isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version), "pyproject version must be SemVer")
    tag = f"v{version}"
    require("## [Unreleased]" in changelog, "CHANGELOG.md must retain [Unreleased]")

    release_match = re.search(
        rf"^## \[{re.escape(version)}\] - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})$",
        changelog,
        re.MULTILINE,
    )
    require(release_match is not None, f"CHANGELOG.md must contain dated [{version}] section")
    release_start = release_match.end()
    next_release = re.search(r"^## \[", changelog[release_start:], re.MULTILINE)
    release_end = release_start + next_release.start() if next_release else len(changelog)
    release_body = changelog[release_start:release_end]
    for heading in ("Summary", "Added", "Changed", "Fixed", "Security", "Validation", "Notes"):
        require(section(release_body, heading) is not None, f"release section is missing non-empty {heading}")

    banner = f"> Current release: `{tag}`. See [CHANGELOG](CHANGELOG.md) for release notes."
    require(banner in readme, "README.md current-release banner is not synchronized")
    require("source/test/bootstrap" in posture, "release posture must keep the source/test/bootstrap ceiling")
    require("not admitted" in posture, "release posture must preserve the admission non-claim")
    require("c0fec92d36b0fd1f6c0c4a9802b37d22cea2c598" in reconciliation, "reconciliation must bind the observed landed baseline")
    require("Complete reachable-commit ledger" in reconciliation, "complete reconciliation ledger is missing")
    require(releasing_path.is_file(), "docs/RELEASING.md is missing")

    print(f"[ok] owner-local release surface is consistent for {tag} ({release_match.group('date')})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
