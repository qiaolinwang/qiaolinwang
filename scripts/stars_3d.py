"""Render two animated 3D views of every star a GitHub user's repos have earned.

stars-galaxy.svg  a tilted, rotating spiral galaxy: one particle per star.
                  distance from the core = arrival order (rings mark new years),
                  colour = repo,
                  height above the disc = hour of day (UTC); newest stars pulse.
stars-city.svg    an isometric city: rows = repos, columns = quarters,
                  tower height = stars that quarter (sqrt scale), and a back
                  wall carrying the running total.

Needs a token: STARS_TOKEN (a personal access token) if set, else GITHUB_TOKEN.
The stargazers REST list refuses anonymous calls, so GraphQL is the fallback.

    python scripts/stars_3d.py <user> <out_dir> [--from-json stars.json]

stars.json, when given, is a list of [starred_at_iso, repo_name] pairs.
"""
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

API = "https://api.github.com"
PALETTE = ["#7dcfff", "#bb9af7", "#9ece6a", "#e0af68", "#f7768e"]
OTHER = "#a9b1d6"
FONT = '"Segoe UI",Helvetica,Arial,sans-serif'


def request(url, token, body=None):
    req = urllib.request.Request(url, data=body, headers={
        "Accept": "application/vnd.github.star+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "stars-3d",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        e.detail = e.read().decode(errors="replace")[:300]
        e.wants = e.headers.get("X-Accepted-GitHub-Permissions", "")
        raise


STARGAZERS = """query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    stargazers(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      edges { starredAt }
    }
  }
}"""


def stargazers_rest(full_name, token):
    dates, page = [], 1
    while True:
        batch = request(f"{API}/repos/{full_name}/stargazers?per_page=100&page={page}", token)
        if not isinstance(batch, list):
            raise RuntimeError(f"unexpected response: {str(batch)[:200]}")
        dates += [s["starred_at"] for s in batch]
        if len(batch) < 100:
            return dates
        page += 1


def stargazers_graphql(full_name, token):
    owner, name = full_name.split("/")
    dates, after = [], None
    while True:
        body = json.dumps({"query": STARGAZERS, "variables": {"owner": owner, "name": name, "after": after}})
        res = request(f"{API}/graphql", token, body.encode())
        if "errors" in res:
            raise RuntimeError(res["errors"][0].get("message", res["errors"]))
        page = res["data"]["repository"]["stargazers"]
        dates += [e["starredAt"] for e in page["edges"]]
        if not page["pageInfo"]["hasNextPage"]:
            return dates
        after = page["pageInfo"]["endCursor"]


def fetch_stars(user, token):
    repos, page = [], 1
    while True:
        batch = request(f"{API}/users/{user}/repos?type=owner&per_page=100&page={page}", token)
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    stars, missing = [], []
    for repo in repos:
        if repo["stargazers_count"] == 0:
            continue
        name = f"{repo['full_name']} ({repo['stargazers_count']} stars)"
        tried = []
        dates = []
        for label, fetch in (("REST", stargazers_rest), ("GraphQL", stargazers_graphql)):
            try:
                dates = fetch(repo["full_name"], token)
                tried.append(f"{label} {len(dates)}")
            except urllib.error.HTTPError as err:
                tried.append(f"{label} HTTP {err.code} (needs: {err.wants or 'not stated'})")
            except RuntimeError as err:
                tried.append(f"{label} error: {err}")
            if dates:
                break
        print(f"{'ok' if dates else 'EMPTY':6} {name}: " + " | ".join(tried))
        if not dates:
            missing.append(repo["stargazers_count"])
        stars += [(d, repo["name"]) for d in dates]
    if missing:
        print(f"::warning::{len(missing)} repos ({sum(missing)} stars) returned no star dates and are left out")
    if not stars:
        sys.exit("GitHub returned no star dates for any repository with this token.")
    return sorted(stars)


def parse(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def shade(c, f):
    return "#" + "".join(f"{min(255, round(int(c[i:i + 2], 16) * f)):02x}" for i in (1, 3, 5))


def repo_colours(stars, top=5):
    ranked = [name for name, _ in Counter(r for _, r in stars).most_common()]
    colours = {name: PALETTE[i] if i < top else OTHER for i, name in enumerate(ranked)}
    return ranked, colours


def twinkles(W, H, seed, n=140):
    rng = random.Random(seed)
    dots = []
    for _ in range(n):
        dots.append(f'<circle class="tw" cx="{rng.uniform(0, W):.0f}" cy="{rng.uniform(0, H):.0f}" '
                    f'r="{rng.choice([0.6, 0.8, 1.0, 1.3])}" '
                    f'style="animation-duration:{rng.uniform(2.5, 7):.1f}s;animation-delay:-{rng.uniform(0, 7):.1f}s"/>')
    return "".join(dots)


def legend(x, y, stars, ranked, colours, top=5):
    counts = Counter(r for _, r in stars)
    rows = [(name, counts[name], colours[name]) for name in ranked[:top]]
    rest = sum(counts[n] for n in ranked[top:])
    if rest:
        rows.append((f"{len(ranked) - top} more repos", rest, OTHER))
    out = [f'<text x="{x}" y="{y}" class="k">REPOSITORIES</text>']
    for i, (name, c, col) in enumerate(rows):
        yy = y + 24 + i * 22
        out.append(f'<circle cx="{x + 6}" cy="{yy - 4}" r="5" fill="{col}"/>'
                   f'<text x="{x + 20}" y="{yy}" class="l">{name}</text>'
                   f'<text x="{x + 190}" y="{yy}" class="n" text-anchor="end">{c}</text>')
    return "".join(out), y + 24 + len(rows) * 22


def render_galaxy(user, stars, now):
    W, H = 900, 480
    cx, cy, R, K = 350, 272, 285, 0.34      # centre, disc radius, squash (camera elevation)
    roll = math.radians(-9)
    period, steps = 90, 24                   # seconds per turn, samples per orbit
    rho_min, core_r = 0.12, 0.16 * R
    ranked, colours = repo_colours(stars)
    t0 = parse(stars[0][0])
    N = len(stars)
    rng = random.Random(42)
    cr, sr = math.cos(roll), math.sin(roll)

    def screen(x, y):
        return cx + x * cr - y * sr, cy + x * sr + y * cr

    def rho_at(rank):  # sqrt keeps the disc evenly filled
        return rho_min + (1 - rho_min) * math.sqrt(rank / N)

    grads = "".join(
        f'<radialGradient id="g{i}"><stop offset="0" stop-color="#fff"/>'
        f'<stop offset=".35" stop-color="{c}"/><stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
        for i, c in enumerate(PALETTE + [OTHER]))
    gid = {c: i for i, c in enumerate(PALETTE + [OTHER])}
    rot = f'transform="rotate({math.degrees(roll):.1f} {cx} {cy})"'

    rings = []
    for year in range(t0.year + 1, now.year + 1):
        first = next((i for i, (iso, _) in enumerate(stars) if parse(iso).year >= year), None)
        if not first:
            continue
        rho = rho_at(first)
        rings.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rho * R:.1f}" ry="{rho * R * K:.1f}" class="ring" {rot}/>')
        ang = 1.9 - 0.45 * (year - t0.year)  # fan the labels out so tight rings stay legible
        lx, ly = screen(rho * R * math.cos(ang), rho * R * K * math.sin(ang))
        rings.append(f'<text x="{lx:.0f}" y="{ly + 12:.0f}" class="yr" text-anchor="middle">{year}</text>')
    rings.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{R}" ry="{R * K:.1f}" class="ring edge" {rot}/>')
    ex, ey = screen(R * math.cos(0.15), R * K * math.sin(0.15))
    rings.append(f'<text x="{ex + 8:.0f}" y="{ey + 4:.0f}" class="yr now">now</text>')

    particles, pulses = [], []
    newest = len(stars) - 3
    for idx, (iso, repo) in enumerate(stars):
        t = parse(iso)
        rho = min(1.0, max(rho_min * 0.6, rho_at(idx + 0.5) + rng.gauss(0, 0.01)))
        arm = idx % 2
        phi0 = arm * math.pi + 3.1 * math.log(rho / rho_min) + rng.gauss(0, 0.16 + 0.22 * (1 - rho))
        hour = t.hour + t.minute / 60
        h = (hour / 24 - 0.5) * 2 * 15 * (1 - 0.45 * rho)
        base = 3.0 + (1.6 if idx >= newest else 0) + rng.uniform(-0.4, 0.6)
        pts, radii, alphas = [], [], []
        for j in range(steps + 1):
            phi = phi0 + 2 * math.pi * j / steps
            depth = math.sin(phi)                          # +1 = nearest the viewer
            x, y = screen(rho * R * math.cos(phi), rho * R * K * depth - h)
            alpha = 0.28 + 0.72 * (depth + 1) / 2
            if depth < 0:                                  # hide behind the bulge
                alpha *= 0.15 + 0.85 * min(1.0, abs(rho * R * math.cos(phi)) / core_r) ** 2
            pts.append(f"{x:.1f} {y:.1f}")
            radii.append(f"{base * (0.7 + 0.45 * (depth + 1) / 2):.2f}")
            alphas.append(f"{alpha:.2f}")
        path = "M" + " L".join(pts)
        motion = f'<animateMotion dur="{period}s" repeatCount="indefinite" calcMode="linear" path="{path}"/>'
        colour = colours[repo]
        particles.append(
            f'<circle r="{radii[0]}" fill="url(#g{gid[colour]})">{motion}'
            f'<animate attributeName="r" dur="{period}s" repeatCount="indefinite" values="{";".join(radii)}"/>'
            f'<animate attributeName="opacity" dur="{period}s" repeatCount="indefinite" values="{";".join(alphas)}"/>'
            f'<title>{repo} · {iso[:10]}</title></circle>')
        if idx >= newest:
            pulses.append(
                f'<circle r="4" fill="none" stroke="{colour}" stroke-width="1.2">{motion}'
                f'<animate attributeName="r" values="3;16" dur="2.4s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values=".9;0" dur="2.4s" repeatCount="indefinite"/></circle>')

    leg, ly = legend(690, 150, stars, ranked, colours)
    key = [
        "outward = later · rings = new year",
        "colour → repository",
        "height above disc → hour (UTC)",
        f"newest pulse · one turn / {period} s",
    ]
    keys = "".join(f'<text x="690" y="{ly + 30 + i * 19}" class="s">{k}</text>' for i, k in enumerate(key))
    last_year = sum(1 for iso, _ in stars if (now - parse(iso)).days < 365)
    sub = f"+{last_year} in the last year · " if last_year else ""

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>{grads}
<radialGradient id="core"><stop offset="0" stop-color="#ffffff"/><stop offset=".25" stop-color="#e6ecff"/>
<stop offset=".6" stop-color="#7aa2f7" stop-opacity=".35"/><stop offset="1" stop-color="#7aa2f7" stop-opacity="0"/></radialGradient>
<radialGradient id="halo"><stop offset="0" stop-color="#7aa2f7" stop-opacity=".22"/>
<stop offset=".7" stop-color="#bb9af7" stop-opacity=".06"/><stop offset="1" stop-color="#bb9af7" stop-opacity="0"/></radialGradient>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#16161e"/><stop offset="1" stop-color="#1f2335"/></linearGradient>
</defs>
<style>
.h{{font:700 30px {FONT};fill:#c0caf5}}
.s{{font:400 13px {FONT};fill:#9aa5ce}}
.k{{font:700 11px {FONT};fill:#565f89;letter-spacing:.12em}}
.l{{font:400 13px {FONT};fill:#c0caf5}}
.n{{font:700 13px {FONT};fill:#c0caf5}}
.yr{{font:400 10px {FONT};fill:#565f89}}
.now{{fill:#9aa5ce}}
.ring{{fill:none;stroke:#3b4261;stroke-width:.8;stroke-dasharray:2 4}}
.edge{{stroke:#565f89;stroke-dasharray:1 3}}
.tw{{fill:#c0caf5;animation:tw ease-in-out infinite alternate}}
@keyframes tw{{from{{opacity:.08}}to{{opacity:.7}}}}
.core{{animation:breathe 6s ease-in-out infinite alternate}}
@keyframes breathe{{from{{opacity:.75}}to{{opacity:1}}}}
</style>
<rect width="{W}" height="{H}" rx="12" fill="url(#bg)"/>
{twinkles(W, H, 3)}
<ellipse cx="{cx}" cy="{cy}" rx="{R * 1.12:.0f}" ry="{R * K * 1.5:.0f}" fill="url(#halo)" {rot}/>
{"".join(rings)}
<ellipse class="core" cx="{cx}" cy="{cy}" rx="{core_r * 1.5:.0f}" ry="{core_r * 0.8:.0f}" fill="url(#core)" {rot}/>
{"".join(particles)}
{"".join(pulses)}
<path fill="#e0af68" transform="translate(30 24) scale(1.35)" d="M12 .6l3.4 7 7.6 1.1-5.5 5.4 1.3 7.6L12 18.1l-6.8 3.6 1.3-7.6L1 8.7l7.6-1.1z"/>
<text x="70" y="50" class="h">{len(stars)} stars</text>
<text x="71" y="72" class="s">{sub}every star @{user}'s repos have earned, since {t0:%b %Y}</text>
{leg}{keys}
</svg>
'''


def render_city(user, stars, now):
    W, H = 900, 460
    ranked, colours = repo_colours(stars)
    rows = ranked[:5] + (["others"] if len(ranked) > 5 else [])
    colours["others"] = OTHER

    def quarter(t):
        return t.year, (t.month - 1) // 3

    t0 = parse(stars[0][0])
    quarters = []
    y, q = quarter(t0)
    while (y, q) <= quarter(now):
        quarters.append((y, q))
        y, q = (y + 1, 0) if q == 3 else (y, q + 1)
    col = {yq: i for i, yq in enumerate(quarters)}
    grid = Counter()
    for iso, repo in stars:
        r = repo if repo in rows else "others"
        grid[(rows.index(r), col[quarter(parse(iso))])] += 1
    per_q = Counter()
    for (_, c), v in grid.items():
        per_q[c] += v
    cmax = max(grid.values())
    total = len(stars)

    n, m = len(quarters), len(rows)
    step, bar, pitch, deep = 10.0, 7.6, 17.0, 12.0
    zmax, zwall, bwall = 100.0, 120.0, -10.0

    def raw(a, b, z):
        return a * 0.97 + b * 0.66, -a * 0.25 + b * 0.44 - z

    A, B = n * step, m * pitch
    corners = [raw(0, bwall, 0), raw(0, bwall, zwall), raw(A, bwall, zwall), raw(A, B, 0), raw(0, B, 0), raw(A, bwall, 0)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    box = (230, 100, W - 90, H - 34)
    k = min((box[2] - box[0]) / (max(xs) - min(xs)), (box[3] - box[1]) / (max(ys) - min(ys)))
    dx = box[0] + ((box[2] - box[0]) - k * (max(xs) - min(xs))) / 2 - k * min(xs)
    dy = box[3] - k * max(ys)

    def xy(a, b, z):
        x, y = raw(a, b, z)
        return dx + k * x, dy + k * y

    def pt(a, b, z):
        x, y = xy(a, b, z)
        return f"{x:.1f},{y:.1f}"

    def poly(fill, pts, extra=""):
        return f'<polygon fill="{fill}" points="{" ".join(pts)}"{extra}/>'

    out = []
    # floor + back wall with the running total
    out.append(poly("#1f2335", [pt(-3, bwall, 0), pt(A + 3, bwall, 0), pt(A + 3, B, 0), pt(-3, B, 0)]))
    out.append(poly("#1a1b2b", [pt(0, bwall, 0), pt(A, bwall, 0), pt(A, bwall, zwall), pt(0, bwall, zwall)],
                    ' stroke="#2f334d" stroke-width=".8"'))
    nice = next(s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000) if total / s <= 5)
    for v in range(nice, total + 1, nice):
        z = zwall * v / total
        out.append(f'<polyline points="{pt(0, bwall, z)} {pt(A, bwall, z)}" class="gl"/>')
        x, y = xy(0, bwall, z)
        out.append(f'<text x="{x - 6:.1f}" y="{y + 3:.1f}" class="yr" text-anchor="end">{v}</text>')
    run, curve = 0, [pt(0, bwall, 0)]
    for i in range(n):
        run += per_q[i]
        curve.append(pt((i + 1) * step, bwall, zwall * run / total))
    out.append(f'<polygon points="{" ".join(curve + [pt(A, bwall, 0)])}" fill="url(#wall)"/>')
    out.append(f'<polyline points="{" ".join(curve)}" class="cum" pathLength="1"/>')
    ex, ey = xy(A, bwall, zwall)
    out.append(f'<text x="{ex + 8:.1f}" y="{ey + 4:.1f}" class="n">{total} total</text>')

    # towers: back row first; within a row the far (later) columns first
    for r in range(m):
        c_hex = colours[rows[r]]
        b0 = r * pitch
        b1 = b0 + deep
        for i in reversed(range(n)):
            a0, a1 = i * step, i * step + bar
            v = grid.get((r, i), 0)
            if not v:
                out.append(poly("#2a2e45", [pt(a0, b0, 0), pt(a1, b0, 0), pt(a1, b1, 0), pt(a0, b1, 0)]))
                continue
            z = 2 + zmax * math.sqrt(v / cmax)
            faces = (poly(shade(c_hex, 0.55), [pt(a0, b0, 0), pt(a0, b1, 0), pt(a0, b1, z), pt(a0, b0, z)])
                     + poly(shade(c_hex, 0.78), [pt(a0, b1, 0), pt(a1, b1, 0), pt(a1, b1, z), pt(a0, b1, z)])
                     + poly(mix(c_hex, "#ffffff", 0.25), [pt(a0, b0, z), pt(a1, b0, z), pt(a1, b1, z), pt(a0, b1, z)]))
            y, q = quarters[i]
            out.append(f'<g class="b" style="animation-delay:{0.15 * r + 0.05 * i:.2f}s">'
                       f'<title>{rows[r]} · {y} Q{q + 1}: {v} star{"s" if v > 1 else ""}</title>{faces}</g>')
        x, y = xy(-26, b0 + deep / 2, 0)
        count = sum(v for (rr, _), v in grid.items() if rr == r)
        out.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" class="l" text-anchor="end" fill="{c_hex}">'
                   f'{rows[r]} <tspan class="n">{count}</tspan></text>')
    for i, (y, q) in enumerate(quarters):
        if q == 0:
            x, yy = xy(i * step, B + 4, 0)
            out.append(f'<text x="{x:.1f}" y="{yy + 12:.1f}" class="yr">{y}</text>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#16161e"/><stop offset="1" stop-color="#1f2335"/></linearGradient>
<linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7dcfff" stop-opacity=".35"/><stop offset="1" stop-color="#7aa2f7" stop-opacity=".02"/></linearGradient>
</defs>
<style>
.h{{font:700 26px {FONT};fill:#c0caf5}}
.s{{font:400 13px {FONT};fill:#9aa5ce}}
.l{{font:600 12px {FONT}}}
.n{{font:700 12px {FONT};fill:#c0caf5}}
.yr{{font:400 10px {FONT};fill:#565f89}}
.gl{{fill:none;stroke:#2f334d;stroke-width:.6;stroke-dasharray:2 3}}
.cum{{fill:none;stroke:#7dcfff;stroke-width:2;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1;animation:draw 2.6s .4s ease-out forwards}}
@keyframes draw{{to{{stroke-dashoffset:0}}}}
.b{{opacity:0;animation:rise .8s cubic-bezier(.2,.9,.3,1.2) forwards}}
@keyframes rise{{from{{opacity:0;transform:translateY(30px)}}to{{opacity:1;transform:translateY(0)}}}}
.tw{{fill:#c0caf5;animation:tw ease-in-out infinite alternate}}
@keyframes tw{{from{{opacity:.05}}to{{opacity:.45}}}}
</style>
<rect width="{W}" height="{H}" rx="12" fill="url(#bg)"/>
{twinkles(W, H, 11, 60)}
<text x="30" y="46" class="h">Where the stars landed</text>
<text x="31" y="68" class="s">stars per quarter × repository · tower height ∝ √stars · back wall = running total</text>
{"".join(out)}
</svg>
'''


def main():
    user, out_dir = sys.argv[1], sys.argv[2]
    if "--from-json" in sys.argv:
        stars = sorted(tuple(s) for s in json.load(open(sys.argv[sys.argv.index("--from-json") + 1])))
    else:
        stars = fetch_stars(user, os.environ.get("STARS_TOKEN") or os.environ["GITHUB_TOKEN"])
    if not stars:
        sys.exit("no stars yet")
    now = datetime.now(timezone.utc)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "stars-galaxy.svg"), "w") as f:
        f.write(render_galaxy(user, stars, now))
    with open(os.path.join(out_dir, "stars-city.svg"), "w") as f:
        f.write(render_city(user, stars, now))


if __name__ == "__main__":
    main()
