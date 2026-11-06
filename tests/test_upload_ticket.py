import os
from pathlib import Path
import shutil
import subprocess

import pytest

from mfhelper.upload_ticket import (
    MAX_UPLOAD_BYTES,
    TicketError,
    mint_ticket,
    verify_ticket,
)

SECRET = "s" * 48
UPLOAD_TOKEN_DIR = Path(__file__).resolve().parents[1] / "deploy" / "vercel" / "upload-token"


def test_ticket_round_trip_carries_login_and_scoped_limit():
    ticket = mint_ticket(SECRET, "mfhelper-owner", now=1_000)

    payload = verify_ticket(SECRET, ticket, now=1_010)

    assert payload["login"] == "mfhelper-owner"
    assert payload["max_bytes"] == MAX_UPLOAD_BYTES
    assert payload["exp"] == 1_120


def test_ticket_expires_after_two_minutes():
    ticket = mint_ticket(SECRET, "mfhelper-owner", now=1_000)

    verify_ticket(SECRET, ticket, now=1_119)
    with pytest.raises(TicketError, match="expired"):
        verify_ticket(SECRET, ticket, now=1_120)


def test_ticket_signed_with_another_secret_is_rejected():
    ticket = mint_ticket("x" * 48, "mfhelper-owner", now=1_000)

    with pytest.raises(TicketError):
        verify_ticket(SECRET, ticket, now=1_001)


def test_tampered_payload_is_rejected():
    ticket = mint_ticket(SECRET, "mfhelper-owner", now=1_000)
    other = mint_ticket(SECRET, "someone-else", now=1_000)
    forged = other.split(".")[0] + "." + ticket.split(".")[1]

    with pytest.raises(TicketError):
        verify_ticket(SECRET, forged, now=1_001)


@pytest.mark.parametrize("bad", [None, 42, "", "abc", "a.b.c", "x" * 3000])
def test_malformed_tickets_are_rejected(bad):
    with pytest.raises(TicketError):
        verify_ticket(SECRET, bad, now=1_001)


def test_short_secret_is_refused_for_minting_and_verifying():
    with pytest.raises(TicketError):
        mint_ticket("short", "mfhelper-owner")
    with pytest.raises(TicketError):
        verify_ticket("short", "a.b")


def test_ticket_minted_in_python_is_accepted_by_the_node_service():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    ticket = mint_ticket(SECRET, "mfhelper-owner")
    env = {
        **os.environ,
        "MFHELPER_TEST_SECRET": SECRET,
        "MFHELPER_TEST_TICKET": ticket,
    }

    result = subprocess.run(
        [node, "--test", "--test-name-pattern=cross-language", "test/ticket.test.js"],
        cwd=UPLOAD_TOKEN_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "cross-language" in result.stdout
    assert "# SKIP" not in result.stdout.split("cross-language")[1].splitlines()[0]
