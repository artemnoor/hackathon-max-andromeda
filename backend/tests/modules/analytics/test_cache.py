from andromeda.modules.analytics.services.cache import AnalyticsResultCache


def test_analytics_cache_is_bounded_and_invalidates_affected_programs() -> None:
    cache = AnalyticsResultCache(max_entries=2)
    first = object()
    second = object()
    third = object()

    cache.put("first", first, program_ids=frozenset({"program:1"}))  # type: ignore[arg-type]
    cache.put("second", second, program_ids=frozenset({"program:2"}))  # type: ignore[arg-type]
    cache.put("third", third, program_ids=frozenset({"program:3"}))  # type: ignore[arg-type]

    assert len(cache) == 2
    assert cache.get("first") is None
    assert cache.get("third") is third

    cache.invalidate(("program:3",))

    assert cache.get("third") is None
    assert cache.get("second") is second
