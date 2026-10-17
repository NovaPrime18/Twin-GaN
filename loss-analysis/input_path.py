"""Supplementary: the 20 A input path the main run does not cover.

The XT60 (J3 pad 2) reaches the fuse (F1 pad 1) on its own net,
Net-(J3-Pin_2), which carries the full 20 A into the board.  It is routed as
an F.Cu pour, so it is solved the same way and folded into a thermal model
that also contains Vdrive, GND and the phase legs, so its heat can spread.
"""
import collections
import math
import numpy as np

from kicad_parse import load_board, extract
from network import (NetNetwork, vertical_edges, node_area_layer, solve_thermal,
                      T_LAYER, ALPHA_CU)
import analyze as A

m = extract(load_board(A.BOARD))

nets = {'Net-(J3-Pin_2)', 'Vdrive', 'GND'}
for c in A.PHASE_PATHS:
    nets.add(c['sw']); nets.add(c['mot'])

th = NetNetwork(m, nets, h=0.5)
extra = []
for c in A.PHASE_PATHS:
    k1, k2 = ('pad', c['shunt'], '1'), ('pad', c['shunt'], '2')
    th.dsu.find(k1); th.dsu.find(k2)
    extra.append((k1, k2, 1.0 / A.SHUNT_G_TH, 'shunt', {'ref': c['shunt']}))
Nth = th.finalise(extra_edges=vertical_edges(th) + extra)
areas, lay = node_area_layer(th)
print(f"thermal model: {Nth} nodes, {len(th.A)} edges")

# --- electrical: 20 A from J3.2 to F1.1 --------------------------------------
e = A.Elec(m, ['Net-(J3-Pin_2)'])
src = e.n.node_at_pad('J3', '2')
snk = e.n.node_at_pad('F1', '1')
print(f"source J3.2 node {src}, sink F1.1 node {snk}, nodes={e.N}, edges={len(e.n.A)}")
print("kinds:", collections.Counter(e.n.kinds))

I = 20.0
Tlook = {}
for it in range(3):
    e.update_T(Tlook)
    P = e.solve({src: I, snk: -I})
    # everything else in proportion to the converged main run, so the thermal
    # background temperature is realistic rather than cold
    Q = np.zeros(Nth)
    a = np.array([th.nid(k) for k in e.n.ek1])
    b = np.array([th.nid(k) for k in e.n.ek2])
    np.add.at(Q, a, P / 2)
    np.add.at(Q, b, P / 2)
    # background warmth from the rest of the board, placed only on outer-layer
    # copper because that is the copper with a direct path to ambient
    scale = 2463.6e-3 / max(P.sum(), 1e-9) * 0.9
    idx = np.where((areas > 0) & ((lay == 0) | (lay == 3)))[0]
    Q[idx] += scale * P.sum() / len(idx)
    T = solve_thermal(th, Q, A.SCEN['tamb'], areas, lay)
    Tlook = {k: T[th.nid(k)] for k in th.dsu.p}
    print(f"  iter {it+1}: P={P.sum()*1000:8.2f} mW  R={(abs(e.n.v[src]-e.n.v[snk])/I)*1000:7.4f} mOhm"
          f"  Tmax={T.max():6.1f} C")

print(f"\nXT60 -> fuse pour: {P.sum()*1000:.1f} mW at 20 A, "
      f"R = {abs(e.n.v[src]-e.n.v[snk])/I*1000:.3f} mOhm")
print(f"  peak node temperature {T.max():.1f} C")

rows = []
for i, (kind, (R0, meta)) in enumerate(zip(e.n.kinds, e.n.metas)):
    Te = max(Tlook.get(e.n.ek1[i], 25.0), Tlook.get(e.n.ek2[i], 25.0))
    Ie = abs(e.n.I[i])
    if kind == 'zone':
        rows.append((e.P[i], Te, Ie, meta['layer'], e.n.h,
                     f"pour cell ({meta['cell'][0]*e.n.h:.1f},{meta['cell'][1]*e.n.h:.1f})"))
    elif kind == 'via':
        v = meta['via']
        rows.append((e.P[i], Te, Ie, meta['layer'], math.pi * v['drill'],
                     f"{v['drill']} mm via @({v['x']:.2f},{v['y']:.2f})"))
    elif kind == 'track':
        rows.append((e.P[i], Te, Ie, meta['layer'], meta['w'],
                     f"({meta['x1']:.2f},{meta['y1']:.2f})->({meta['x2']:.2f},{meta['y2']:.2f})"))
rows.sort(key=lambda r: -r[1])
print(f"\n  {'T(C)':>7}{'P(mW)':>9}{'I(A)':>7}{'w(mm)':>7}  layer   detail")
for p, Te, Ie, l, w, d in rows[:12]:
    print(f"  {Te:7.1f}{p*1000:9.3f}{Ie:7.2f}{w:7.2f}  {l:<7} {d}")

by = collections.Counter()
for i, k in enumerate(e.n.kinds):
    by[k] += e.P[i]
print("\npower by kind:", {k: f"{v*1000:.1f} mW" for k, v in by.items()})
