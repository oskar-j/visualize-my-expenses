"""CHANGELOG.md: every version has a section, because the release depends on it.

On master, the section for the version in pyproject.toml becomes the GitHub
Release notes. Checking it here makes a version bump without its section fail
in the pull request, before the merge, instead of on master after it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
RELEASES = "https://github.com/oskar-j/visualize-my-expenses/releases/tag/v"

# Exactly `## [x.y.z]`, with nothing after it: the release workflow finds the
# section by comparing whole lines.
HEADING = re.compile(r"^## \[(.+)\]$", re.MULTILINE)
LINK = re.compile(r"^\[[^\]]+\]: ")


def project_version() -> str:
    # pyproject.toml rather than vme.__version__: an editable install that was
    # not reinstalled after a bump still reports the previous version.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"$', text, re.MULTILINE).group(1)


def section(changelog: str, version: str) -> str:
    """The text under ``## [version]``, up to the next heading or the link list."""
    lines = changelog.splitlines()
    start = lines.index(f"## [{version}]") + 1
    end = next((i for i in range(start, len(lines))
                if lines[i].startswith("## ") or LINK.match(lines[i])), len(lines))
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


class TestChangelog:
    def test_the_current_version_has_a_section(self, changelog):
        version = project_version()
        assert version in HEADING.findall(changelog), (
            f"pyproject.toml is at {version}, but CHANGELOG.md has no section for it. "
            f'Add a "## [{version}]" line (nothing after it) at the top, describing the release.')
        assert section(changelog, version).strip(), f'"## [{version}]" in CHANGELOG.md is empty.'

    def test_the_newest_version_comes_first(self, changelog):
        headings = HEADING.findall(changelog)
        try:
            versions = [Version(v) for v in headings]
        except InvalidVersion as exc:
            pytest.fail(f"CHANGELOG.md has a heading that is not a version: {exc}")
        assert versions == sorted(versions, reverse=True), (
            f"CHANGELOG.md sections must run newest first, but they run {headings}.")
        assert headings[0] == project_version(), (
            f"The top section of CHANGELOG.md is {headings[0]}, "
            f"but pyproject.toml is at {project_version()}.")

    def test_every_section_links_to_its_release(self, changelog):
        lines = set(changelog.splitlines())
        missing = [f"[{v}]: {RELEASES}{v}" for v in HEADING.findall(changelog)
                   if f"[{v}]: {RELEASES}{v}" not in lines]
        assert not missing, (
            "Add these links to the bottom of CHANGELOG.md, so each heading points "
            "to its GitHub Release:\n" + "\n".join(missing))
