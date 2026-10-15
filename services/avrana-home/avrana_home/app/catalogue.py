"""The route/service/help tables, loaded from ONE place. Standard library only.

For now the single source is `services/avrana-portal/portal.py` (the deployed portal stays
untouched). This module loads that file BY PATH at application start (never at import time) and
exposes frozen, typed copies. At cut-over the tables move into this application and only
`load()` changes; every consumer already goes through this seam. The parity test forces the two
to stay equal until then.

Text in the tables is trusted static markup (entities such as `&amp;` and `&nbsp;`, inline
apostrophes) and is rendered as written, exactly as the portal does. It is wrapped in `Trusted`
so the templates, which autoescape everything else, can tell it apart. Nothing from a request
ever becomes `Trusted`.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

_REQUIRED = ("SERVICES", "CHOOSERS", "HELP", "INTERSTITIALS", "SSO_INIT", "HOME_ORDER",
             "HELP_SLUGS", "ALIASES", "ACCOUNT_URL", "SIGNOUT_URL", "SERVICE_VARIANTS",
             "CHOOSER_PARTS")


class CatalogueError(RuntimeError):
    pass


class Trusted(str):
    """A str from the static tables that templates render without escaping. Mirrors
    markupsafe.Markup's contract without importing it; the template layer converts."""
    __slots__ = ()


def _t(value):
    """Recursively mark every string in a static table as Trusted; tuples stay tuples."""
    if isinstance(value, str):
        return Trusted(value)
    if isinstance(value, (list, tuple)):
        return tuple(_t(v) for v in value)
    return value


@dataclass(frozen=True)
class ServiceEntry:
    groups: Tuple[str, ...]          # holding ANY one grants access
    label: Trusted
    desc: Trusted
    path: str
    host: str
    grouped: bool = False            # the portal's table gave a tuple/list of groups (variants apply)

    def allows(self, groups) -> bool:
        return any(g in groups for g in self.groups)


@dataclass(frozen=True)
class ChooserEntry:
    label: Trusted
    desc: Trusted
    path: str
    members: Tuple[str, ...]


@dataclass(frozen=True)
class HelpTopic:
    group: str
    label: Trusted
    host: str
    platforms: tuple                 # ((platform, ((client, store, url, steps), ...)), ...)
    slug: str


@dataclass(frozen=True)
class Catalogue:
    services: Tuple[ServiceEntry, ...]
    choosers: Tuple[ChooserEntry, ...]
    help_topics: Tuple[HelpTopic, ...]
    interstitials: Dict[str, Tuple[Trusted, str]]
    sso_init: Dict[str, str]
    home_order: Tuple[str, ...]
    aliases: Dict[str, str]
    account_url: str
    signout_url: str
    service_variants: Dict[str, Dict[Tuple[str, ...], Tuple[Trusted, Trusted]]]
    chooser_parts: Dict[str, Dict[str, str]]

    # ---- lookups: same semantics as portal.by_path / chooser_by_path / chooser_members ----
    def service(self, path):
        return next((s for s in self.services if s.path == path), None)

    def chooser(self, path):
        return next((c for c in self.choosers if c.path == path), None)

    def permitted(self, groups):
        return [s for s in self.services if s.allows(groups)]

    def chooser_members(self, chooser, groups):
        out = []
        for mpath in chooser.members:
            svc = self.service(mpath)
            if svc and svc.allows(groups):
                out.append(svc)
        return out

    def service_copy(self, svc: ServiceEntry, groups):
        """(label, desc) of a service as THIS viewer should read it (portal.service_copy, AVR-430)."""
        variants = self.service_variants.get(svc.path)
        if variants and svc.grouped:
            held = tuple(g for g in svc.groups if g in groups)
            if held in variants:
                return variants[held]
        return svc.label, svc.desc

    def chooser_subtitle(self, chooser: ChooserEntry, groups) -> Trusted:
        """The chooser tile subtitle, built only from the members this viewer may open
        (portal.chooser_subtitle, AVR-430)."""
        parts = self.chooser_parts.get(chooser.path)
        if parts is None:
            return chooser.desc
        words = []
        for svc in self.chooser_members(chooser, groups):
            word = parts.get(svc.path)
            if word and word not in words:
                words.append(word)
        if not words:
            return chooser.desc
        text = " &amp; ".join(words)
        return Trusted(text[0].upper() + text[1:])

    def help_permitted(self, groups):
        return [h for h in self.help_topics if h.group in groups]

    def help_by_slug(self, slug):
        return next((h for h in self.help_topics if h.slug == slug), None)

    def redirect_target(self, svc: ServiceEntry) -> str:
        """Fixed table value, never request input."""
        return self.sso_init.get(svc.path, f"https://{svc.host}")

    def all_redirect_targets(self):
        return {self.redirect_target(s) for s in self.services}


def load(path) -> Catalogue:
    path = Path(path)
    if not path.is_file():
        raise CatalogueError("catalogue source not found")
    spec = importlib.util.spec_from_file_location("avrana_portal_tables", path)
    if spec is None or spec.loader is None:
        raise CatalogueError("catalogue source cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:   # a broken table file must stop startup, not half-load
        raise CatalogueError(f"catalogue source failed to load ({type(exc).__name__})") from None
    missing = [n for n in _REQUIRED if not hasattr(module, n)]
    if missing:
        raise CatalogueError("catalogue source lacks: " + ", ".join(missing))

    services = []
    for grp, label, desc, spath, host in module.SERVICES:
        groups = tuple(grp) if isinstance(grp, (tuple, list)) else (grp,)
        services.append(ServiceEntry(groups, Trusted(label), Trusted(desc), spath, host,
                                     isinstance(grp, (tuple, list))))
    choosers = tuple(ChooserEntry(Trusted(label), Trusted(desc), cpath, tuple(members))
                     for label, desc, cpath, members in module.CHOOSERS)
    slugs = module.HELP_SLUGS
    topics = []
    for grp, label, host, platforms in module.HELP:
        if label not in slugs:
            raise CatalogueError("help topic without a slug")
        topics.append(HelpTopic(grp, Trusted(label), host, _t(platforms), slugs[label]))
    return Catalogue(
        services=tuple(services), choosers=choosers, help_topics=tuple(topics),
        interstitials={k: (Trusted(v[0]), str(v[1])) for k, v in module.INTERSTITIALS.items()},
        sso_init=dict(module.SSO_INIT), home_order=tuple(module.HOME_ORDER),
        aliases=dict(module.ALIASES), account_url=str(module.ACCOUNT_URL),
        signout_url=str(module.SIGNOUT_URL),
        service_variants={p: {tuple(k): (Trusted(v[0]), Trusted(v[1])) for k, v in d.items()}
                          for p, d in module.SERVICE_VARIANTS.items()},
        chooser_parts={p: dict(d) for p, d in module.CHOOSER_PARTS.items()})
