"""
Tests for the async sliding-window RateLimiter (PERF-02 / TEST-06).

Pins the async rate-limiter contract deterministically:

- is_allowed is a coroutine guarded by an asyncio.Lock (PERF-02): it no
  longer blocks the event loop with a threading.Lock.
- The sliding window is driven by an injectable time_func clock (TEST-06),
  so over-limit rejection and window expiry are provable without any
  wall-clock waits. This whole module sleeps for zero real seconds.

Every test injects a mutable clock via time_func and advances it by hand;
coroutines are driven with asyncio.run so the tests stay sync-shaped under
pytest's strict asyncio mode.
"""

import asyncio
import inspect

from netops_mcp.middleware.rate_limiter import RateLimiter


class TestRateLimiter:
    """Deterministic behavior of the async sliding-window rate limiter."""

    def test_over_limit_no_sleep(self):
        """First two requests pass, the third is rejected — no sleeping."""
        clock = {"t": 1000.0}
        rl = RateLimiter(
            requests_per_window=2,
            window_seconds=60,
            time_func=lambda: clock["t"],
        )

        assert asyncio.run(rl.is_allowed("c"))[0] is True
        assert asyncio.run(rl.is_allowed("c"))[0] is True
        assert asyncio.run(rl.is_allowed("c"))[0] is False

    def test_sliding_window_expiry(self):
        """Advancing the injected clock past the window resets the limit."""
        clock = {"t": 1000.0}
        rl = RateLimiter(
            requests_per_window=2,
            window_seconds=60,
            time_func=lambda: clock["t"],
        )

        # Reach the limit within the window.
        assert asyncio.run(rl.is_allowed("c"))[0] is True
        assert asyncio.run(rl.is_allowed("c"))[0] is True
        assert asyncio.run(rl.is_allowed("c"))[0] is False

        # Advance past the window: the oldest requests fall out and the
        # limiter admits traffic again — deterministic, no wall-clock wait.
        clock["t"] += 61
        assert asyncio.run(rl.is_allowed("c"))[0] is True

    def test_is_allowed_is_coroutine(self):
        """is_allowed is async (asyncio.Lock, non-blocking hot path)."""
        assert inspect.iscoroutinefunction(RateLimiter.is_allowed)

    def test_remaining_count_decrements(self):
        """The remaining-request count decreases with each admitted call."""
        clock = {"t": 500.0}
        rl = RateLimiter(
            requests_per_window=3,
            window_seconds=60,
            time_func=lambda: clock["t"],
        )

        allowed_1, remaining_1, _ = asyncio.run(rl.is_allowed("c"))
        allowed_2, remaining_2, _ = asyncio.run(rl.is_allowed("c"))

        assert allowed_1 is True and remaining_1 == 2
        assert allowed_2 is True and remaining_2 == 1

    def test_reset_time_reflects_oldest_request(self):
        """When over limit the reset_time counts down from the oldest hit."""
        clock = {"t": 2000.0}
        rl = RateLimiter(
            requests_per_window=1,
            window_seconds=60,
            time_func=lambda: clock["t"],
        )

        assert asyncio.run(rl.is_allowed("c"))[0] is True

        # 10s later, still inside the window: rejected with ~50s to reset.
        clock["t"] += 10
        allowed, remaining, reset_time = asyncio.run(rl.is_allowed("c"))
        assert allowed is False
        assert remaining == 0
        assert reset_time == 50

    def test_clients_are_isolated(self):
        """Separate client_ids maintain independent windows."""
        clock = {"t": 0.0}
        rl = RateLimiter(
            requests_per_window=1,
            window_seconds=60,
            time_func=lambda: clock["t"],
        )

        assert asyncio.run(rl.is_allowed("client-a"))[0] is True
        # A different client is unaffected by client-a hitting its limit.
        assert asyncio.run(rl.is_allowed("client-b"))[0] is True
        assert asyncio.run(rl.is_allowed("client-a"))[0] is False

    def test_get_stats_is_async_and_reports_usage(self):
        """get_stats is a coroutine and reflects admitted requests."""
        assert inspect.iscoroutinefunction(RateLimiter.get_stats)

        clock = {"t": 100.0}
        rl = RateLimiter(
            requests_per_window=5,
            window_seconds=60,
            time_func=lambda: clock["t"],
        )

        asyncio.run(rl.is_allowed("c"))
        asyncio.run(rl.is_allowed("c"))
        stats = asyncio.run(rl.get_stats("c"))

        assert stats == {
            "limit": 5,
            "remaining": 3,
            "used": 2,
            "window_seconds": 60,
        }


class TestBucketEviction:
    """Memory must stay bounded as clients/IPs rotate (idle-bucket eviction).

    Without eviction the ``requests`` map grows one entry per distinct client
    forever, because per-client cleanup only runs when that client is seen
    again — an unauthenticated caller rotating source IPs could exhaust memory.
    """

    def test_empty_bucket_is_dropped_by_cleanup(self):
        """When a bucket's only request ages out, the key is removed, not left as []."""
        clock = {"t": 1000.0}
        rl = RateLimiter(requests_per_window=5, window_seconds=60, time_func=lambda: clock["t"])

        asyncio.run(rl.is_allowed("ip:a"))
        assert "ip:a" in rl.requests

        clock["t"] += 61
        rl._cleanup_old_requests("ip:a", clock["t"])
        assert "ip:a" not in rl.requests

    def test_rotating_clients_are_swept(self):
        """A window-spanning sweep evicts stale buckets from rotated identifiers."""
        clock = {"t": 1000.0}
        rl = RateLimiter(requests_per_window=100, window_seconds=60, time_func=lambda: clock["t"])

        # 50 one-shot clients within one window: first call sweeps the empty
        # map, the rest just record -> 50 live buckets.
        for i in range(50):
            asyncio.run(rl.is_allowed(f"ip:{i}"))
        assert len(rl.requests) == 50

        # Advance past the window; a single new client triggers the periodic
        # sweep, which evicts all 50 now-stale buckets.
        clock["t"] += 61
        asyncio.run(rl.is_allowed("ip:new"))
        assert len(rl.requests) == 1
        assert "ip:new" in rl.requests

    def test_active_client_survives_sweep_that_evicts_idle(self):
        """The sweep keeps clients with an in-window hit and drops only idle ones."""
        clock = {"t": 1000.0}
        rl = RateLimiter(requests_per_window=100, window_seconds=60, time_func=lambda: clock["t"])

        asyncio.run(rl.is_allowed("ip:idle"))  # last seen at t=1000
        clock["t"] += 30
        asyncio.run(rl.is_allowed("ip:active"))  # last seen at t=1030

        # t=1070: idle's 1000 is stale (cutoff 1010), active's 1030 is fresh,
        # and >1 window since the last sweep so the sweep fires.
        clock["t"] += 40
        asyncio.run(rl.is_allowed("ip:active"))

        assert "ip:idle" not in rl.requests
        assert "ip:active" in rl.requests
