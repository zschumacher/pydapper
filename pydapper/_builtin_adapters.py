"""Eager bootstrap of the first-party adapters at package import.

Temporary and intentionally unchanged in behavior: ``pydapper/__init__.py``
still imports this module, and importing it still registers the same eight
stable adapter names in the same order it always has.

The registration definitions themselves now live in ``_adapter_providers`` as
one callback per adapter name, so this module is only the ordering and the
invocation. There is deliberately no ``register_adapter()`` call and no
command-class import left here -- duplicating either would give first-party
registration two sources of truth right before the next #468 slice moves the
same callbacks behind ``pydapper.adapters`` entry points and deletes this eager
bootstrap.
"""

from ._adapter_providers import _FIRST_PARTY_ADAPTER_PROVIDERS


def _register_builtin_adapters() -> None:
    for register_provider in _FIRST_PARTY_ADAPTER_PROVIDERS:
        register_provider()


_register_builtin_adapters()
