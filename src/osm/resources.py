"""Centralised package-resource access via :mod:`importlib.resources`.

``dashboard.py`` and ``polygons.py`` historically loaded their data
files (``templates/dashboard.html`` and ``zones/*.geojson``) by
constructing ``Path(__file__).parent / ...``. That works for the
common case of an unpacked wheel installed by pip, but it is fragile
for non-filesystem import backends (zipapps, pyOxidizer, frozen
distributions). The ``importlib.resources`` API is the documented
idiom for accessing package data in a backend-independent way.

The two helpers here are intentionally minimal — a thin shim over
``resources.files()`` so callers don't have to repeat the boilerplate
or deal with the materialisation question themselves.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path


def read_text_resource(package: str, name: str) -> str:
    """Return the UTF-8 text content of a packaged resource.

    Suitable for templates and other small text payloads that are read
    once and held in memory. For large or streaming reads, prefer
    :func:`resource_path`.
    """
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


@contextmanager
def resource_path(package: str, name: str) -> Iterator[Path]:
    """Yield a filesystem :class:`Path` for a packaged resource.

    Some import backends materialise resources to a tempfile inside
    the context manager and clean up afterwards, so callers MUST do
    their reading inside the ``with`` block::

        with resource_path("osm.zones", "blue-ash-montgomery.geojson") as p:
            geojson = json.loads(p.read_text(encoding="utf-8"))
    """
    target = resources.files(package).joinpath(name)
    with resources.as_file(target) as path:
        yield path
