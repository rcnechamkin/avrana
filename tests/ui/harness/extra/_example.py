"""Example registry hook. Ignored by the harness because the file name starts with an underscore.

To register pages for another service, copy this file to `extra/<name>.py` (no leading underscore),
or point the environment variable UI_HARNESS_EXTRA at your own file. The harness imports it and calls
`register(registry)`. Nothing in the harness has to be edited.

Then record the page's known findings with
    python -B tests/ui/harness/update_baseline.py --write --add-new
(the first time, with a reviewer's agreement) or, better, fix them so the baseline never grows.

Audible connector (templates are Jinja2, which is not in the standard library): render inside the
callable, and convert a missing dependency into `Unavailable`:

    def render_connect():
        try:
            import jinja2
        except ImportError:
            raise Unavailable("jinja2 is not installed; pip install jinja2 to render the Audible pages")
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES), autoescape=True)
        html = env.get_template("connect.html").render(brand="AVRANA", error=None, notice=None, asset_v="x")
        return Rendered(200, html, css=[(STATIC / "style.css").read_text(encoding="utf-8")])

The stylesheet is linked, not inline, so pass its text in `css=` for the static layer; for the browser
layer also pass `assets={"/static/style.css": bytes}` (served at /a/static/style.css) or inline the
stylesheet into the HTML you return.

services/avrana-home (FastAPI + Jinja): the same pattern, rendering a route with a fixture
principal, e.g. via fastapi.testclient.TestClient inside the callable (guarded by try/except ImportError).
"""
from harness.pages import Identity, Page, Rendered

MEMBER = Identity(id="member-a", klass="member", groups=("example-group",), username="member-a",
                  name="Member A", email="a@example.test")


def register(registry):
    registry.add(Page(
        service="example", page="hello", identity=MEMBER, visibility="authorized",
        render=lambda: Rendered(200, "<!doctype html><html lang=en><title>Hello</title><main><h1>Hello</h1></main></html>"),
        tags=("example",),
        forbid=("Secret service",),      # tokens this identity must never see on this page
    ))
