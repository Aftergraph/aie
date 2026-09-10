"""Monotonic revocation-freshness monitor.

Spec: docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md
Plan: docs/superpowers/plans/2026-09-09-revocation-freshness-watermark.md Task 2
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RevocationFreshnessMonitor:
    """Tracks authenticated authority watermarks and determines freshness.

    Freshness requires ALL of:
    - At least one valid watermark received from the expected source
    - Watermark age <= freshness_ttl (measured by local monotonic clock)
    - Local canonical revocation digest matches the authority digest
      carried by the most recent accepted watermark
    """

    def __init__(
        self,
        *,
        expected_source_gateway: str,
        freshness_ttl: float,
        local_revocation_state_sha256: Callable[[], str],
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        ttl = float(freshness_ttl)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("freshness_ttl must be finite and > 0")
        self.expected_source_gateway = expected_source_gateway
        self.freshness_ttl = ttl
        self.local_revocation_state_sha256 = local_revocation_state_sha256
        self.monotonic_clock = monotonic_clock
        self.last_sequence: int | None = None
        self.last_confirmed_monotonic: float | None = None
        self.authority_revocation_state_sha256: str | None = None
        self._lock = threading.RLock()

    def _read_monotonic(self) -> float | None:
        try:
            current = float(self.monotonic_clock())
        except Exception:  # noqa: BLE001 - external clock must fail closed
            return None
        return current if math.isfinite(current) else None

    def observe(
        self,
        *,
        source_gateway: str,
        sequence: int,
        revocation_state_sha256: str,
    ) -> bool:
        """Accept a watermark if valid and strictly newer than the last accepted.

        Returns True if the watermark was accepted (state updated).
        Returns False if rejected (wrong source, bad sequence, stale, malformed digest).
        """
        if source_gateway != self.expected_source_gateway:
            return False
        if type(sequence) is not int or sequence < 0:
            return False
        if (
            not isinstance(revocation_state_sha256, str)
            or _SHA256_RE.fullmatch(revocation_state_sha256) is None
        ):
            return False

        with self._lock:
            if self.last_sequence is not None and sequence <= self.last_sequence:
                return False
            current = self._read_monotonic()
            if current is None:
                return False
            self.last_sequence = sequence
            self.last_confirmed_monotonic = current
            self.authority_revocation_state_sha256 = revocation_state_sha256
            return True

    def is_fresh(self) -> bool:
        """Determine whether the current revocation view is fresh.

        Requires confirmed state, age within TTL, and digest equality.
        Any exception or non-finite monotonic reading results in stale.
        """
        with self._lock:
            if (
                self.last_confirmed_monotonic is None
                or self.authority_revocation_state_sha256 is None
            ):
                return False

            current = self._read_monotonic()
            if current is None:
                return False
            age = current - self.last_confirmed_monotonic
            if age < 0 or age > self.freshness_ttl:
                return False

            try:
                local_digest = self.local_revocation_state_sha256()
            except Exception:  # noqa: BLE001 - external digest provider must fail closed
                return False

            current_after_digest = self._read_monotonic()
            if current_after_digest is None:
                return False
            age_after_digest = current_after_digest - self.last_confirmed_monotonic
            if age_after_digest < 0 or age_after_digest > self.freshness_ttl:
                return False

            return local_digest == self.authority_revocation_state_sha256

    def status(self) -> dict[str, object]:
        """Return observable monitor state for diagnostics."""
        with self._lock:
            current = self._read_monotonic()
            age = (
                None
                if self.last_confirmed_monotonic is None or current is None
                else current - self.last_confirmed_monotonic
            )
            return {
                "fresh": self.is_fresh(),
                "last_sequence": self.last_sequence,
                "age_seconds": age,
                "authority_revocation_state_sha256": self.authority_revocation_state_sha256,
            }
