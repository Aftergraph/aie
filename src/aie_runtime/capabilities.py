from __future__ import annotations

from collections.abc import Iterable


def _prefix(selector: str) -> str | None:
    # AIE v0.4 candidate selector: only one wildcard form is legal, a single
    # trailing '*'. Any '*' elsewhere is treated literally and therefore does
    # not broaden authority.
    if selector.endswith("*") and "*" not in selector[:-1]:
        return selector[:-1]
    return None


def capability_allows(selector: str, capability: str) -> bool:
    prefix = _prefix(selector)
    if prefix is not None:
        return capability.startswith(prefix)
    return selector == capability


def capability_set_allows(selectors: Iterable[str], capability: str) -> bool:
    return any(capability_allows(selector, capability) for selector in selectors)


def capability_selector_within(parent: str, child: str) -> bool:
    parent_prefix = _prefix(parent)
    child_prefix = _prefix(child)
    if parent_prefix is None:
        return child == parent
    if child_prefix is not None:
        return child_prefix.startswith(parent_prefix)
    return child.startswith(parent_prefix)


def capability_set_attenuates(parent: Iterable[str], child: Iterable[str]) -> bool:
    parents = tuple(parent)
    return all(any(capability_selector_within(p, c) for p in parents) for c in child)
