"""Render the copper loss/temperature result as a compact SVG heat map.

Runs the electro-thermal pipeline once, caches the result as raster.json, then
rasterises every copper element onto a 1 mm grid (max temperature per cell) and
emits one batched <path> per colour level.  Re-run with --reuse to re-render
from the cache without re-solving.
"""
import collections
import json
import math
import os
import sys
import numpy as np

from kicad_parse import load_board, extract
from network import (NetNetwork, vertical_edges, node_area_layer, solve_thermal,
                      T_LAYER, H, xf)
import analyze as A

SCALE = 8.0
X0, Y0 = 49.0, 49.0
W = (152 - 49) * SCALE
CACHE = '/home/tj/Twin-GaN/loss-analysis/raster.json'

STOPS = [(0.00, (35, 60, 140)), (0.22, (0, 160, 190)), (0.42, (35, 175, 70)),
         (0.62, (225, 205, 45)), (0.80, (240, 120, 25)), (1.00, (205, 20, 25))]


def col(T, tmin=25.0, tmax=95.0):
    u = min(1.0, max(0.0, (T - tmin) / (tmax - tmin)))
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if u <= b:
            t = (u - a) / (b - a) if b > a else 0.0
            return tuple(int(ca[i] + t * (cb[i] - ca[i])) for i in range(3))
    return STOPS[-1][1]


def solve():
    m = extract(load_board(A.BOARD))
    jobs = A.build_all(m, A.SCEN['phase_rms'])

    allnets = {'Vdrive', 'GND', 'Net-(J3-Pin_2)'}
    for c in A.PHASE_PATHS:
        allnets.add(c['sw']); allnets.add(c['mot'])
    th = NetNetwork(m, allnets, h=H)
    extra = []
    for c in A.PHASE_PATHS:
        k1, k2 = ('pad', c['shunt'], '1'), ('pad', c['shunt'], '2')
        th.dsu.find(k1); th.dsu.find(k2)
        extra.append((k1, k2, 1.0 / A.SHUNT_G_TH, 'shunt', {'ref': c['shunt']}))
    Nth = th.finalise(extra_edges=vertical_edges(th) + extra)
    areas, lay = node_area_layer(th)

    e_in = A.Elec(m, ['Net-(J3-Pin_2)'])
    src_in, snk_in = e_in.n.node_at_pad('J3', '2'), e_in.n.node_at_pad('F1', '1')
    jobs.append(('Input J3->F1', e_in,
                 lambda e: {src_in: 20.0, snk_in: -20.0}))

    Tlook = {}
    for it in range(3):
        Q = np.zeros(Nth)
        total = 0.0
        for tag, e, inj in jobs:
            e.update_T(Tlook)
            P = e.solve(inj(e))
            total += P.sum()
            a = np.array([th.nid(k) for k in e.n.ek1])
            b = np.array([th.nid(k) for k in e.n.ek2])
            np.add.at(Q, a, P / 2)
            np.add.at(Q, b, P / 2)
        Tvec = solve_thermal(th, Q, A.SCEN['tamb'], areas, lay)
        Tlook = {k: Tvec[th.nid(k)] for k in th.dsu.p}
        print(f'  iter {it+1}: {total*1000:8.1f} mW  Tmax {Tvec.max():6.1f} C')

    # ---- rasterise to 1 mm cells, max temperature per cell -----------------
    grid = {}
    callouts = {}

    def put(x, y, T):
        k = (int(x // 1.0), int(y // 1.0))
        if T > grid.get(k, -1e9):
            grid[k] = T

    for tag, e, inj in jobs:
        n = e.n
        for i, (kind, (R0, meta)) in enumerate(zip(n.kinds, n.metas)):
            Te = float(max(Tlook.get(n.ek1[i], 25.0), Tlook.get(n.ek2[i], 25.0)))
            if kind == 'zone':
                ix, iy = meta['cell']
                put((ix + 0.5) * H, (iy + 0.5) * H, Te)
                if meta['dir'] == 'x':
                    put((ix + 1.0) * H, (iy + 0.5) * H, Te)
                else:
                    put((ix + 0.5) * H, (iy + 1.0) * H, Te)
            elif kind == 'track':
                L = math.hypot(meta['x2'] - meta['x1'], meta['y2'] - meta['y1'])
                steps = max(1, int(L / 0.5) + 1)
                for s in range(steps + 1):
                    t = s / steps
                    x = meta['x1'] + (meta['x2'] - meta['x1']) * t
                    y = meta['y1'] + (meta['y2'] - meta['y1']) * t
                    put(x, y, Te)
                    if meta['w'] >= 1.0 and L > 0:
                        nx = -(meta['y2'] - meta['y1']) / L * meta['w'] / 2
                        ny = (meta['x2'] - meta['x1']) / L * meta['w'] / 2
                        for sgn in (-1, 1):
                            put(x + sgn * nx, y + sgn * ny, Te)
                if meta['w'] >= 1.5:
                    key = f"{tag} {meta['w']:.1f}mm"
                    if key not in callouts or Te > callouts[key]['T']:
                        callouts[key] = dict(
                            T=Te, x=(meta['x1'] + meta['x2']) / 2,
                            y=(meta['y1'] + meta['y2']) / 2,
                            label=f"{tag} · {meta['w']:.1f} mm trace",
                            I=float(abs(n.I[i])), P=float(e.P[i]))
            elif kind == 'via':
                v = meta['via']; put(v['x'], v['y'], Te)
            elif kind == 'shunt':
                k1, k2 = n.ek1[i], n.ek2[i]
                if k1[0] == 'pad' and k2[0] == 'pad':
                    pa = next(q for q in m['pads'] if q['ref'] == k1[1] and q['num'] == k1[2])
                    pb = next(q for q in m['pads'] if q['ref'] == k2[1] and q['num'] == k2[2])
                    ax, ay = xf(pa['fp_x'], pa['fp_y'], pa['fp_rot'], pa['x'], pa['y'])
                    bx, by = xf(pb['fp_x'], pb['fp_y'], pb['fp_rot'], pb['x'], pb['y'])
                    for s in range(9):
                        t = s / 8
                        put(ax + (bx - ax) * t, ay + (by - ay) * t, Te)
                    key = f"shunt {k1[1]}"
                    if key not in callouts or Te > callouts[key]['T']:
                        callouts[key] = dict(T=Te, x=(ax + bx) / 2, y=(ay + by) / 2,
                                              label=f"shunt {k1[1]} · 2 mΩ",
                                              I=float(abs(n.I[i])), P=float(e.P[i]))

    data = dict(grid=[[k[0], k[1], round(v, 2)] for k, v in grid.items()],
                callouts=list(callouts.values()))
    json.dump(data, open(CACHE, 'w'))
    print(f'  cached {len(grid)} cells, {len(callouts)} callouts -> raster.json')
    return data


def render(data):
    grid = {(a, b): c for a, b, c in data['grid']}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{W:.0f}" '
           f'viewBox="0 0 {W:.0f} {W:.0f}" font-family="DejaVu Sans, sans-serif">',
           f'<rect width="{W:.0f}" height="{W:.0f}" fill="#0b0e13"/>']
    x1, y1 = (51 - X0) * SCALE, (51 - Y0) * SCALE
    side = 99 * SCALE
    out.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{side:.1f}" height="{side:.1f}" '
               f'fill="#12161d" stroke="#39434f" stroke-width="2"/>')

    buckets = collections.defaultdict(list)
    s = SCALE
    for (ix, iy), T in grid.items():
        c = col(T)
        buckets[(int(c[0] / 8) * 8, int(c[1] / 8) * 8, int(c[2] / 8) * 8)].append((ix, iy))
    for c, cells in buckets.items():
        d = ' '.join(f'M{ix * s:.0f} {iy * s:.0f}h{s:.0f}v{s:.0f}h-{s:.0f}z'
                     for ix, iy in cells)
        out.append(f'<path d="{d}" fill="rgb({c[0]},{c[1]},{c[2]})"/>')

    for c in sorted(data['callouts'], key=lambda c: -c['T'])[:4]:
        ax, ay = (c['x'] - X0) * SCALE, (c['y'] - Y0) * SCALE
        out.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="12" fill="none" '
                   f'stroke="#ffffff" stroke-width="1.8" opacity="0.9"/>')
        right = ax < W * 0.60
        tx = ax + 16 if right else ax - 16
        anchor = 'start' if right else 'end'
        out.append(f'<text x="{tx:.0f}" y="{ay - 5:.0f}" fill="#ffffff" font-size="12" '
                   f'font-weight="bold" text-anchor="{anchor}">{c["label"]}</text>')
        out.append(f'<text x="{tx:.0f}" y="{ay + 10:.0f}" fill="#ffd479" font-size="12" '
                   f'text-anchor="{anchor}">{c["T"]:.0f} °C · {c["I"]:.2f} A rms · '
                   f'{c["P"] * 1000:.0f} mW</text>')

    out.append(f'<g transform="translate(20,{W - 100:.0f})">')
    out.append('<rect x="0" y="0" width="330" height="84" rx="6" fill="#0b0e13" '
               'stroke="#39434f"/>')
    out.append('<text x="14" y="22" fill="#e6edf3" font-size="13" font-weight="bold">'
               'Copper temperature — 54 V, 20 A DC, 25 °C ambient</text>')
    for k in range(70):
        T = 25 + k / 69 * 70
        cc = col(T)
        out.append(f'<rect x="{14 + k * 3.3:.1f}" y="33" width="3.5" height="13" '
                   f'fill="rgb({cc[0]},{cc[1]},{cc[2]})"/>')
    for v in (25, 43, 60, 78, 95):
        xx = 14 + (v - 25) / 70 * 235
        out.append(f'<text x="{xx:.0f}" y="62" fill="#8b98a8" font-size="10" '
                   f'text-anchor="middle">{v}°C</text>')
    out.append('<text x="14" y="77" fill="#8b98a8" font-size="10">'
               'max temperature per 1 mm cell across all four copper layers · '
               '1 oz outer / 0.5 oz inner</text>')
    out.append('</g></svg>')

    path = '/home/tj/Twin-GaN/loss-analysis/loss-heatmap.svg'
    open(path, 'w').write('\n'.join(out))
    print(f'wrote {path} ({os.path.getsize(path) / 1024:.0f} kB)')


if __name__ == '__main__':
    if '--reuse' in sys.argv and os.path.exists(CACHE):
        data = json.load(open(CACHE))
        print(f'reusing {len(data["grid"])} cached cells')
    else:
        data = solve()
    render(data)
