"""Private lazy discovery catalog for the ``pydapper.adapters`` entry-point group.

This module only discovers and caches entry-point *metadata*. It never calls
``EntryPoint.load()``, never invokes provider callbacks, and never mutates the
adapter registry. Later #468 slices consume the catalog to load providers.

Everything here is private; nothing is exported from the package root.
"""

from __future__ import annotations

import importlib.metadata
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_ENTRY_POINT_GROUP = "pydapper.adapters"


@dataclass(frozen=True)
class _AdapterProviderDescriptor:
    """Metadata for one installed provider of an adapter entry point.

    Retains the original entry point so a later slice can load it, plus the
    exact adapter name and the provider distribution's display name for
    precedence decisions and error reporting.
    """

    name: str
    distribution: str
    entry_point: importlib.metadata.EntryPoint


_catalog: Mapping[str, tuple[_AdapterProviderDescriptor, ...]] | None = None
_catalog_lock = threading.Lock()


def _validate_provider_name(name: object) -> str:
    if not isinstance(name, str):
        raise TypeError(
            f"Adapter entry-point name in group {_ENTRY_POINT_GROUP!r} must be a string, got {type(name).__name__}"
        )
    if not name or name != name.strip():
        raise ValueError(
            f"Adapter entry-point name {name!r} in group {_ENTRY_POINT_GROUP!r} "
            "must be non-empty and have no surrounding whitespace"
        )
    return name


def _distribution_display_name(entry_point: importlib.metadata.EntryPoint) -> str:
    dist = getattr(entry_point, "dist", None)
    dist_name = getattr(dist, "name", None) if dist is not None else None
    if not isinstance(dist_name, str) or not dist_name or dist_name != dist_name.strip():
        raise ValueError(
            f"Entry point {getattr(entry_point, 'name', None)!r} in group {_ENTRY_POINT_GROUP!r} "
            "has no usable distribution name"
        )
    return dist_name


def _enumerate_entry_points() -> tuple[importlib.metadata.EntryPoint, ...]:
    try:
        # the group keyword is supported on every project Python version (3.10+) and avoids the
        # deprecated dict-shaped no-argument result
        entry_points = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)
    except Exception as exc:
        raise ValueError(f"Failed to enumerate entry points for group {_ENTRY_POINT_GROUP!r}") from exc
    return tuple(entry_points)


def _build_catalog() -> Mapping[str, tuple[_AdapterProviderDescriptor, ...]]:
    grouped: dict[str, list[_AdapterProviderDescriptor]] = {}
    for entry_point in _enumerate_entry_points():
        if entry_point.group != _ENTRY_POINT_GROUP:
            continue
        name = _validate_provider_name(entry_point.name)
        descriptor = _AdapterProviderDescriptor(
            name=name,
            distribution=_distribution_display_name(entry_point),
            entry_point=entry_point,
        )
        grouped.setdefault(name, []).append(descriptor)

    # sort by stable metadata so enumeration order can never influence later selection; duplicates
    # are retained for the later collision-resolution slice
    return MappingProxyType(
        {
            name: tuple(sorted(providers, key=lambda d: (d.distribution, d.entry_point.value)))
            for name, providers in sorted(grouped.items())
        }
    )


def _get_provider_catalog() -> Mapping[str, tuple[_AdapterProviderDescriptor, ...]]:
    """Return the cached provider catalog, building it on first access.

    Discovery is serialized by a lock so concurrent first access enumerates
    metadata exactly once. A failed build raises without caching anything.
    """
    global _catalog
    catalog = _catalog
    if catalog is not None:
        return catalog
    with _catalog_lock:
        if _catalog is None:
            _catalog = _build_catalog()
        return _catalog


def _reset_provider_catalog_for_tests() -> None:
    global _catalog
    with _catalog_lock:
        _catalog = None
