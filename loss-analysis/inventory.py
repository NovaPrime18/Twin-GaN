import collections
import math
import json
from kicad_parse import load_board, extract

BOARD = '/home/tj/Twin-GaN/Twin-GaN-VESC.kicad_pcb'
m = extract(load_board(BOARD))

COPPER_T = 0.035  # mm, 1 oz on every layer
RHO = 1.72e-8    # ohm-m at 20 C


def seg_len(t):
    d = math.hypot(t['x2'] - t['x1'], t['y2'] - t['y1'])
    if t.get('arc') and t.get('mx') is not None:
        # crude arc length via 3-point circumcircle
        ax, ay = t['x1'], t['y1']
        bx, by = t['mx'], t['my']
        cx, cy = t['x2'], t['y2']
        d1 = math.hypot(bx - ax, by - ay)
        d2 = math.hypot(cx - bx, cy - by)
        d3 = math.hypot(cx - ax, cy - ay)
        area = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
        if area < 1e-9:
            return d3
        R = d1 * d2 * d3 / (4 * area)
        # central angle
        import math as _m
        ang = 2 * _m.asin(min(1.0, d3 / (2 * R)))
        return R * ang
    return d


# ---- aggregate by net ----
by_net = collections.defaultdict(lambda: {
    'len': collections.Counter(),      # (layer,width) -> mm
    'vias': 0, 'zone_area': 0.0, 'zone_layers': set(),
    'pads': collections.Counter(), 'nets': set(),
})

for t in m['tracks']:
    n = t['net'] or '<none>'
    key = (t['layer'], t['w'])
    by_net[n]['len'][key] += seg_len(t)

for v in m['vias']:
    n = v['net'] or '<none>'
    by_net[n]['vias'] += 1

for z in m['zones']:
    n = z['net'] or '<none>'
    a = 0.0
    for fp in z['filled']:
        pts = fp['pts']
        s = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            s += x1 * y2 - x2 * y1
        a += abs(s) / 2
        by_net[n]['zone_layers'].add(fp['layer'])
    by_net[n]['zone_area'] += a

for p in m['pads']:
    if p['net']:
        by_net[p['net']]['pads'][p['ref']] += 1

# ---- report ----
rows = []
for n, d in by_net.items():
    if n == '<none>':
        continue
    total_len = sum(d['len'].values())
    rows.append((n, total_len, d))

rows.sort(key=lambda r: -r[1])

print(f"{'net':<22}{'trk_len_mm':>11}{'vias':>6}{'zone_mm2':>10}  widths")
print('-' * 100)
for n, tl, d in rows[:45]:
    ws = collections.Counter()
    for (lay, w), L in d['len'].items():
        ws[w] += L
    wstr = ', '.join(f'{w}mm:{L:.0f}' for w, L in sorted(ws.items(), key=lambda x: -x[1])[:4])
    print(f"{n:<22}{tl:>11.1f}{d['vias']:>6}{d['zone_area']:>10.0f}  {wstr}")

print()
print('=== ZONES ===')
for z in sorted(m['zones'], key=lambda z: -sum(
        abs(sum(p['pts'][i][0] * p['pts'][(i + 1) % len(p['pts'])][1] -
                p['pts'][(i + 1) % len(p['pts'])][0] * p['pts'][i][1]
                for i in range(len(p['pts'])))) / 2 for p in z['filled'])):
    a = 0.0
    for fp in z['filled']:
        pts = fp['pts']
        s = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            s += x1 * y2 - x2 * y1
        a += abs(s) / 2
    print(f"  net={z['net']:<16} layers={z['layers']} prio={z['priority']:<3} filled_area={a:8.1f} mm2  polys={len(z['filled'])}")

print()
print('=== connectors / power components ===')
for f in m['footprints']:
    v = (f['value'] or '') + ' ' + (f['ref'] or '')
    if any(k in v.upper() for k in ['XT60', 'MR30', 'XT30', 'EPC23102', 'INDUCT', 'SHUNT']):
        print(f"  {f['ref']:<8} {str(f['value']):<24} ({f['x']:.1f},{f['y']:.1f}) rot={f['rot']} {f['layer']}")

json.dump({n: {'len': {f'{k[0]}|{k[1]}': v for k, v in d['len'].items()},
               'vias': d['vias'], 'zone_area': d['zone_area'],
               'zone_layers': sorted(d['zone_layers'])}
           for n, d in by_net.items()},
          open('/home/tj/Twin-GaN/loss-analysis/net_inventory.json', 'w'), indent=1)
print('\nwrote net_inventory.json')
