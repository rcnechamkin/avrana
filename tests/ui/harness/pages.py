"""The page registry: one declarative entry per (service, page, identity).

An entry says how to produce the page offline (a callable returning `Rendered`), who is looking
at it, what they are expected to see, and tags. The static checks (`static_checks.py`) and the
browser layer (`serve.py` + `check.mjs`) both read this registry and nothing else, so a page that
is registered is checked in both layers.

Adding pages (no harness internals need editing)
-----------------------------------------------
Drop a module into `tests/ui/harness/extra/` (any name not starting with "_") that defines

    def register(registry): ...

and call `registry.add(Page(...))` inside it. Modules listed in the environment variable
`UI_HARNESS_EXTRA` (os.pathsep separated file paths) are loaded the same way, so a service that
lives outside this directory can keep its adapter next to its own code. A tiny example is in
`extra/_example.py` (ignored because of the underscore).

Rules for a render callable
---------------------------
* Offline only: no network, no database, no live service. Use fixture identities and data.
* Return `Rendered(status, html)`. Raise `Unavailable("why")` when the page cannot be produced on
  this tree (a service not merged yet, an optional dependency missing). Such entries are listed as
  "unavailable" and are never failures.
* Do not import third-party packages at module import time. Import inside the render callable and
  convert ImportError into `Unavailable`.
* The HTML must be self-contained (inline CSS) for the browser layer; if a stylesheet is linked,
  pass its text in `Rendered.css` so the static layer can read it and list the file under
  `Rendered.assets` (path -> bytes) so `serve.py` can serve it.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parents[2]

VISIBILITIES = ("authorized", "denied", "empty", "degraded")


class Unavailable(Exception):
    """The page cannot be produced on this tree. Reported, never a failure."""


@dataclass(frozen=True)
class Identity:
    id: str                       # short, stable, used in finding ids ("none", "books", "admin")
    klass: str                    # anonymous | member | admin
    groups: tuple = ()
    username: str = ""
    name: str = ""
    email: str = ""
    label: str = ""


@dataclass
class Rendered:
    status: int
    html: str
    css: list = field(default_factory=list)      # text of linked stylesheets, when the HTML links them
    assets: dict = field(default_factory=dict)   # served path -> bytes
    notes: list = field(default_factory=list)    # how it was produced, shown in the index


@dataclass
class Page:
    service: str
    page: str
    identity: Identity
    visibility: str                          # authorized | denied | empty | degraded
    render: Callable[[], Rendered]
    tags: tuple = ()
    forbid: tuple = ()                       # tokens this page must not contain (leak check)
    expect_status: int | None = None         # default: 200, or 404 when visibility is "denied"
    needs_js: bool = False                   # browser layer keeps JavaScript on for this page
    note: str = ""

    def __post_init__(self):
        if self.visibility not in VISIBILITIES:
            raise ValueError(f"unknown visibility {self.visibility!r}")

    @property
    def key(self):
        return f"{self.service}/{self.page}/{self.identity.id}"

    @property
    def wanted_status(self):
        if self.expect_status is not None:
            return self.expect_status
        return 404 if self.visibility == "denied" else 200

    def produce(self):
        """(Rendered, None) or (None, reason) when unavailable. Cached per Page."""
        if not hasattr(self, "_cache"):
            try:
                self._cache = (self.render(), None)
            except Unavailable as e:
                self._cache = (None, str(e) or "unavailable")
        return self._cache


class Registry:
    def __init__(self):
        self._pages: list[Page] = []
        self.load_errors: list[str] = []

    def add(self, page: Page):
        if any(p.key == page.key for p in self._pages):
            raise ValueError(f"duplicate registry key {page.key}")
        self._pages.append(page)
        return page

    def pages(self, service=None):
        return [p for p in self._pages if service is None or p.service == service]

    def services(self):
        return sorted({p.service for p in self._pages})


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extra_module_paths():
    paths = sorted(p for p in (HARNESS_DIR / "extra").glob("*.py") if not p.name.startswith("_")) \
        if (HARNESS_DIR / "extra").is_dir() else []
    for item in filter(None, os.environ.get("UI_HARNESS_EXTRA", "").split(os.pathsep)):
        paths.append(Path(item))
    return paths


def build_registry(extra=True) -> Registry:
    """The full registry: portal + Kindle adapters, then any extra modules."""
    from . import adapters
    reg = Registry()
    adapters.register_portal(reg)
    adapters.register_kindle(reg)
    if extra:
        for i, path in enumerate(extra_module_paths()):
            try:
                mod = _load_module(path, f"ui_harness_extra_{i}_{path.stem}")
                mod.register(reg)
            except Exception as e:  # a broken hook must not hide the rest of the registry
                reg.load_errors.append(f"{path.name}: {type(e).__name__}: {e}")
    return reg
