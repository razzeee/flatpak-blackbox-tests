# SPDX-License-Identifier: LGPL-2.1-or-later
"""Remote configuration contracts, observed through separate client processes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer

RemoteRow = tuple[str, str, str | None, str]


def remote_cli_args(operation: str, arguments: tuple[str, ...]) -> list[str] | None:
    """Return CLI arguments, or None for operations handled by the driver."""
    if operation in ("remote-create", "remote-edit"):
        name, url, title, priority = arguments
        if operation == "remote-create":
            return ["remote-add", "--user", "--no-gpg-verify",
                    f"--title={title}", f"--prio={priority}", name, url]
        return ["remote-modify", "--user", f"--url={url}",
                f"--title={title}", f"--prio={priority}", name]
    if operation == "remote-list":
        if arguments:
            raise ValueError("remote-list takes no arguments")
        return ["remotes", "--user", "--show-disabled", "--columns=name,url,title,priority"]
    if operation == "remote-delete":
        name, = arguments
        return ["remote-delete", "--user", name]
    return None


def _rows(driver: Driver, operation: str, *arguments: str) -> list[RemoteRow]:
    output = driver.success(operation, *arguments)
    rows: list[RemoteRow] = []
    for line in output.splitlines():
        fields = line.split("\t")
        driver.check(len(fields) == 4, f"{operation}: expected four TSV fields, got {line!r}")
        name, url, title, priority = fields
        # Only the library protocol has a NULL marker. CLI values stay literal.
        normalized_title = None if driver.kind == "library" and title == r"\N" else title
        rows.append((name, url, normalized_title, priority))
    return rows


def _expect_remotes(driver: Driver, expected: list[RemoteRow], context: str,
                    *, ordered: bool = True) -> None:
    actual = _rows(driver, "remote-list")
    matches = actual == expected if ordered else (
        len(actual) == len(expected) and set(actual) == set(expected)
    )
    driver.check(matches, f"{context}: expected remotes {expected!r}, got {actual!r}")
    if driver.kind == "library":
        for row in expected:
            queried = _rows(driver, "remote-query", row[0])
            driver.check(queried == [row],
                         f"{context}: lookup of {row[0]} returned {queried!r}, expected {row!r}")


def remote_configuration(driver: Driver, repository: RepositoryServer, url: str,
                         fixture: FixtureManifest) -> None:
    """Exercise isolated user remotes before the runner's usual fixture setup."""
    repository.version = "A"
    # Names must remain distinct while properties and priority order change.
    first = "remote-z-first"
    second = "remote-a-second"
    second_url = f"{url}/"
    changed_url = f"{url}/changed-location"
    first_row: RemoteRow = (first, url, "First remote title", "20")
    second_row: RemoteRow = (second, second_url, "Second remote title", "20")

    _expect_remotes(driver, [], "fresh user installation")
    driver.success("remote-create", first, url, "First remote title", "20")
    _expect_remotes(driver, [first_row], "first add persisted")
    driver.success("remote-create", second, second_url, "Second remote title", "20")
    _expect_remotes(driver, [first_row, second_row], "fresh remote properties", ordered=False)

    # Equal-priority ordering is a separate contract, so its failure cannot
    # prevent these independent persistence checks from executing.
    driver.success("remote-edit", first, url, "First remote title", "10")
    first_row = (first, url, "First remote title", "10")
    _expect_remotes(driver, [second_row, first_row], "descending priority after lowering first")

    if driver.kind == "library":
        present = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
        missing = f"app/{fixture['app']}.Missing/{fixture['arch']}/{fixture['branch']}"
        driver.check(driver.success("remote-ref-query", first, present) == present,
                     "remote ref lookup must reach the populated repository")
        result = driver.call("remote-ref-query", first, missing)
        driver.check(result.returncode == 5 and result.stdout == ""
                     and "error domain=" in result.stderr,
                     f"missing remote ref must return NULL and REF_NOT_FOUND: {result!r}")

    # Change just priority first, proving URL/title survive an unrelated edit.
    driver.success("remote-edit", first, url, "First remote title", "30")
    first_row = (first, url, "First remote title", "30")
    _expect_remotes(driver, [first_row, second_row], "priority change reverses order")

    driver.success("remote-edit", first, changed_url, "Revised remote title", "30")
    first_row = (first, changed_url, "Revised remote title", "30")
    _expect_remotes(driver, [first_row, second_row], "URL and title edits persisted")

    if driver.kind == "library":
        driver.success("remote-clear-title", first)
        first_row = (first, changed_url, None, "30")
        _expect_remotes(driver, [first_row, second_row], "NULL title persists as unset")

    driver.success("remote-delete", first)
    _expect_remotes(driver, [second_row], "deletion persists and other remote survives")
    if driver.kind == "library":
        result = driver.call("remote-query", first)
        driver.check(result.returncode == 1 and result.stdout == ""
                     and "error domain=" in result.stderr,
                     f"deleted remote lookup must return NULL with an error: {result!r}")
        _expect_remotes(driver, [second_row], "missing lookup leaves other remote intact")


def remote_priority_order(driver: Driver, repository: RepositoryServer, url: str,
                          fixture: FixtureManifest) -> None:
    """Check the documented library priority and insertion-order tie contract."""
    rows: list[RemoteRow] = [
        ("remote-z-first", url, "Earlier tied remote", "20"),
        ("remote-a-second", url, "Later tied remote", "20"),
        ("remote-low", url, "Lower priority remote", "10"),
    ]
    _expect_remotes(driver, [], "fresh user installation")
    for name, remote_url, title, priority in rows:
        assert title is not None
        driver.success("remote-create", name, remote_url, title, priority)
    _expect_remotes(driver, rows, "documented priority order and fresh insertion-order ties")
