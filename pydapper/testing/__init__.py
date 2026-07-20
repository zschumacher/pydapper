"""Reusable, framework-neutral testing helpers shipped with the pydapper distribution.

Nothing in this package is exported from the ``pydapper`` package root. Import the
documented helpers explicitly, for example::

    from pydapper.testing.adapter_conformance import run_core_sync

Everything importable under ``pydapper.testing`` uses only the standard library and
pydapper core: no pytest, no optional database drivers, and no repository test
utilities.
"""
