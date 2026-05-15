import re
from pathlib import Path

d = Path(__file__).parent
inject_css = '  <link rel="stylesheet" href="/hq/_base.css" />\n'
inject_script = '  <script src="/hq/_components.js"></script>\n'

for p in sorted(d.glob("*.html")):
    if p.name == "tasks.html":
        continue
    t = p.read_text(encoding="utf-8")
    orig = t
    if "/hq/_base.css" not in t and "/hq/style.css" in t:
        t = t.replace(
            '<link rel="stylesheet" href="/hq/style.css" />',
            '<link rel="stylesheet" href="/hq/style.css" />\n' + inject_css,
            1,
        )
    if "/hq/_components.js" not in t:
        if '<script src="hq-global.js"></script>' in t:
            t = t.replace(
                '<script src="hq-global.js"></script>',
                inject_script + '  <script src="hq-global.js"></script>',
                1,
            )
        elif '<script src="hq-mobile.js"></script>' in t:
            t = t.replace(
                '<script src="hq-mobile.js"></script>',
                inject_script + '  <script src="hq-mobile.js"></script>',
                1,
            )
    if 'aside class="sidebar"' in t and '<nav class="nav">' in t:
        t = re.sub(
            r'<nav class="nav">[\s\S]*?</nav>',
            '<nav class="nav"></nav>',
            t,
            count=1,
        )
    if t != orig:
        p.write_text(t, encoding="utf-8")
        print("patched", p.name)

print("done")
