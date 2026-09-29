from unittest.mock import MagicMock

from andromeda.composition.container import AndromedaContainer
from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.jevql.adapter import JevQLAdapter
from andromeda.infrastructure.jev_tree.adapter import JevTreeAdapter


def test_enabled_jevql_is_wired_into_active_analytics_executor() -> None:
    container = AndromedaContainer(
        engine=MagicMock(),
        settings=Settings(jevql_enabled=True),
    )

    executor = container.analytics_executor()

    assert isinstance(executor._semantic_predicate_port, JevQLAdapter)


def test_disabled_jevql_keeps_analytics_executor_deterministic() -> None:
    container = AndromedaContainer(
        engine=MagicMock(),
        settings=Settings(jevql_enabled=False),
    )

    executor = container.analytics_executor()

    assert executor._semantic_predicate_port is None


def test_enabled_jev_tree_is_wired_into_active_entity_resolver() -> None:
    container = AndromedaContainer(
        engine=MagicMock(),
        settings=Settings(jev_tree_enabled=True),
    )

    resolver = container.entity_resolver()

    assert resolver._hierarchical is not None
    assert isinstance(resolver._hierarchical._port, JevTreeAdapter)


def test_disabled_jev_tree_bypasses_provider_in_entity_resolver() -> None:
    container = AndromedaContainer(
        engine=MagicMock(),
        settings=Settings(jev_tree_enabled=False),
    )

    resolver = container.entity_resolver()

    assert resolver._hierarchical is None
