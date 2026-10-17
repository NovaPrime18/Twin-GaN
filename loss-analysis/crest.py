"""Crest-factor correction for the switched (chopped) FET currents.

The DC solve injects the *average* drain current, 3.333 A per half-bridge.  But
the copper immediately at a FET carries that phase current chopped by PWM, and
over a fundamental cycle at full modulation its rms is 2x the average.  The
bus, where all six contribute, stays at the average.

Attribution: solve once per FET in isolation; an element fed by a single FET
gets the 2x rms factor, anything shared keeps the DC average.
"""
import collections
import numpy as np

from kicad_parse import load_board, extract
from network import NetNetwork, vertical_edges, node_area_layer, solve_thermal
import analyze as A

m = extract(load_board(A.BOARD))
per_ch = A.SCEN['i_dc_ch'] / 3.0
CREST = 2.0

# ---- thermal background: all power nets -------------------------------------
nets = {'Vdrive', 'GND', 'Net-(J3-Pin_2)'}
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


def attribute(netname, sink_refs, sink_pad, source_pad):
    """Return per-edge rms multiplier from single-FET solves."""
    e = A.Elec(m, [netname])
    base_inj = {}
    for f in A.FETS:
        base_inj[e.n.node_at_pad(f, sink_pad)] = base_inj.get(e.n.node_at_pad(f, sink_pad), 0) - per_ch
    base_inj[e.n.node_at_pad(*source_pad)] = +A.SCEN['i_dc_total']
    e.update_T({})
    e.solve(base_inj)
    Ibase = e.n.I.copy()
    e._base_inj = base_inj

    If = np.zeros((len(A.FETS), len(Ibase)))
    for j, f in enumerate(A.FETS):
        inj = {e.n.node_at_pad(f, sink_pad): -per_ch,
               e.n.node_at_pad(*source_pad): +per_ch}
        e.solve(inj)
        If[j] = e.n.I
    # how many FETs feed this element
    mx = np.abs(If).max(axis=0)
    nact = (np.abs(If) > 0.1 * np.maximum(mx, 1e-12)).sum(axis=0)
    mult = np.where(nact <= 1, CREST, 1.0)
    return e, Ibase, mult, nact


print('Attributing Vdrive ...')
ev, Iv, mv, nv = attribute('Vdrive', A.FETS, '10', ('F1', '2'))
print(f'  elements fed by a single FET: {int((nv<=1).sum())} of {len(nv)}  '
      f'({100*(nv<=1).mean():.1f} %)')
print('Attributing GND ...')
eg, Ig, mg, ng = attribute('GND', A.FETS, '8', ('J3', '1'))
print(f'  elements fed by a single FET: {int((ng<=1).sum())} of {len(ng)}  '
      f'({100*(ng<=1).mean():.1f} %)')

# ---- run the thermal loop with corrected rms currents -----------------------
Tlook = {}
for it in range(3):
    Q = np.zeros(Nth)
    for e, mult in ((ev, mv), (eg, mg)):
        e.update_T(Tlook)
        e.solve(e._base_inj)          # refresh: n.I still held the last single-FET solve
        I = e.n.I * mult
        P = I ** 2 * e.n.R0 * e.rm
        e.Pc = P
        a = np.array([th.nid(k) for k in e.n.ek1])
        b = np.array([th.nid(k) for k in e.n.ek2])
        np.add.at(Q, a, P / 2)
        np.add.at(Q, b, P / 2)
    # rest of the board: use the converged main-run numbers as background
    bg = 2463.6e-3 - ev.Pc.sum() - eg.Pc.sum()
    pos = np.where((areas > 0) & ((lay == 0) | (lay == 3)))[0]
    Q[pos] += max(bg, 0.0) / len(pos)
    T = solve_thermal(th, Q, A.SCEN['tamb'], areas, lay)
    Tlook = {k: T[th.nid(k)] for k in th.dsu.p}
    print(f'  iter {it+1}: Vdrive {ev.Pc.sum()*1000:7.1f} mW  '
          f'GND {eg.Pc.sum()*1000:7.1f} mW  Tmax {T.max():6.1f} C')

for name, e, mult in (('Vdrive', ev, mv), ('GND', eg, mg)):
    Te = np.array([max(Tlook.get(e.n.ek1[i], 25.0), Tlook.get(e.n.ek2[i], 25.0))
                    for i in range(len(e.n.A))])
    order = np.argsort(-Te)[:6]
    print(f'\n{name}: hottest elements with rms crest correction '
          f'(P total {e.Pc.sum()*1000:.1f} mW)')
    print(f"  {'T(C)':>7}{'P(mW)':>9}{'I_rms':>8}{'x':>5}  kind   detail")
    for i in order:
        k = e.n.kinds[i]
        meta = e.n.metas[i][1]
        if k == 'zone':
            d = f"pour cell ({meta['cell'][0]*0.5:.1f},{meta['cell'][1]*0.5:.1f})"
        elif k == 'via':
            v = meta['via']; d = f"via @({v['x']:.2f},{v['y']:.2f})"
        elif k == 'track':
            t = meta; d = f"({t['x1']:.1f},{t['y1']:.1f})->({t['x2']:.1f},{t['y2']:.1f})"
        else:
            continue
        print(f"  {Te[i]:7.1f}{e.Pc[i]*1000:9.4f}{abs(e.n.I[i])*mult[i]:8.2f}"
              f"{mult[i]:5.1f}  {k:<6} {d}")
