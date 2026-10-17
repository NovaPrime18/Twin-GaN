"""Twin-GaN PCB copper loss + temperature analysis.

Scenario: 54 V in, 20 A DC total, split equally between the two drivers
(10 A per channel), 25 C ambient, 10 minutes (= steady state).

Currents
--------
Vdrive / GND bus : 20 A total, 3.333 A DC average per half-bridge.
Phase legs       : I_ph,rms = I_dc,ch / (1.0607 * m * cos phi); at full
                   modulation and unity power factor that is 9.43 A rms for a
                   10 A channel -- the *minimum* phase current compatible with
                   the stated DC current, so the optimistic end of the range.

Method
------
Electrical: nodal solve on the real copper geometry (tracks, vias, pads and
a 0.5 mm mesh of every copper pour), 1 oz outer / 0.5 oz inner, with
temperature-dependent resistivity, iterated against the thermal solve.

Thermal: same topology as a conduction network -- copper in-plane, FR4
vertically between layers, outer copper rejecting to ambient.  This captures
plane spreading and short-trace heat sinking, which the plain IPC formula
does not.
"""
import collections
import math
import numpy as np

from kicad_parse import load_board, extract
from network import (NetNetwork, T_LAYER, LAYER_ORDER, K_CU, H_SURF, K_FR4,
                     vertical_edges, node_area_layer, solve_thermal,
                     sheet_R, via_R, ALPHA_CU)

BOARD = '/home/tj/Twin-GaN/Twin-GaN-VESC.kicad_pcb'
H = 0.5

SCEN = dict(vbat=54.0, i_dc_total=20.0, i_dc_ch=10.0,
            phase_rms=9.43, tamb=25.0, minutes=10.0)

FETS = ['U2', 'U5', 'U6', 'U18', 'U26', 'U27']

PHASE_PATHS = [
    dict(tag='ch1-U', fet='U2',  sw='Net-(U2-Phase)',  mot='/Phase/Phase U',  shunt='R97',  conn=('J1', '1')),
    dict(tag='ch1-V', fet='U6',  sw='Net-(U6-Phase)',  mot='/Phase/Phase V',  shunt='R98',  conn=('J1', '2')),
    dict(tag='ch1-W', fet='U18', sw='Net-(U18-Phase)', mot='/Phase/Phase W',  shunt='R99',  conn=('J1', '3')),
    dict(tag='ch2-U', fet='U5',  sw='Net-(U28-+)',     mot='/Phase1/Phase U', shunt='R100', conn=('J11', '1')),
    dict(tag='ch2-V', fet='U26', sw='Net-(U26-Phase)', mot='/Phase1/Phase V', shunt='R101', conn=('J11', '2')),
    dict(tag='ch2-W', fet='U27', sw='Net-(U27-Phase)', mot='/Phase1/Phase W', shunt='R102', conn=('J11', '3')),
]

A_BOARD = 99e-3 * 99e-3
R_BOARD = 1.0 / (H_SURF * 2 * A_BOARD)      # K/W, both faces
SHUNT_R = 0.002
SHUNT_G_TH = 0.05                            # W/K, 1206 body
SHUNT_TCR = 50e-6                            # 1/K, alloy, not copper


# ---------------------------------------------------------------- IPC refs
def dt_ipc2152(I, w_mm, t_mm, layer):
    """Brooks & Adam closed form fit to IPC-2152 (the one KiCad itself uses)."""
    W = w_mm / 0.0254
    Th = t_mm / 0.0254
    if layer in ('F.Cu', 'B.Cu'):
        K, a, b, c = 215.3, 2.0, -1.15, -1.0
    else:
        oz = t_mm / 0.035
        if oz < 0.75:
            K, a, b, c = 120.0, 2.0, -1.10, -1.52
        elif oz < 1.5:
            K, a, b, c = 200.0, 1.9, -1.10, -1.52
        else:
            K, a, b, c = 300.0, 2.0, -1.15, -1.52
    return K * (I ** a) * (W ** b) * (Th ** c)


def dt_ipc2221(I, w_mm, t_mm, layer):
    A_mil = (w_mm * t_mm) * 1550.003
    k = 0.048 if layer in ('F.Cu', 'B.Cu') else 0.024
    return (I / (k * A_mil ** 0.725)) ** (1 / 0.44)


# ---------------------------------------------------------------- electrical
class Elec:
    """One electrical sub-problem, kept alive so the thermal loop can re-solve."""

    def __init__(self, model, nets, extra=()):
        self.nets = nets
        self.n = NetNetwork(model, nets, h=H)
        self.N = self.n.finalise(extra_edges=extra)
        self.rm = np.ones(len(self.n.A))

    def update_T(self, Tlook):
        Te = np.array([max(Tlook.get(k1, 20.0), Tlook.get(k2, 20.0))
                       for k1, k2 in zip(self.n.ek1, self.n.ek2)])
        rm = 1.0 + ALPHA_CU * (Te - 20.0)
        for i, k in enumerate(self.n.kinds):
            if k == 'shunt':
                rm[i] = 1.0 + SHUNT_TCR * (Te[i] - 20.0)
        self.rm = rm
        self.n.G = 1.0 / (self.n.R0 * rm)

    def solve(self, inj):
        self.n.solve(inj, tol=1e-10, iters=80000, verbose=False)
        self.P = self.n.I ** 2 * self.n.R0 * self.rm
        self.I = self.n.I
        return self.P

def build_all(model, phase_rms):
    """Build every electrical sub-problem once."""
    jobs = []
    # Vdrive
    vd = Elec(model, ['Vdrive'])
    per_ch = SCEN['i_dc_ch'] / 3.0

    def inj_vd(e):
        n = e.n
        d = {n.node_at_pad('F1', '2'): +SCEN['i_dc_total']}
        for f in FETS:
            k = n.node_at_pad(f, '10')
            d[k] = d.get(k, 0) - per_ch
        return d
    jobs.append(('Vdrive', vd, inj_vd))

    gd = Elec(model, ['GND'])

    def inj_gnd(e):
        n = e.n
        d = {}
        for f in FETS:
            k = n.node_at_pad(f, '8')
            d[k] = d.get(k, 0) + per_ch
        for ref in ('1', '3'):
            k = n.node_at_pad('J3', ref)
            d[k] = d.get(k, 0) - SCEN['i_dc_total'] / 2
        return d
    jobs.append(('GND', gd, inj_gnd))

    for cfg in PHASE_PATHS:
        sh = cfg['shunt']
        ek1, ek2 = ('pad', sh, '1'), ('pad', sh, '2')
        e = Elec(model, [cfg['sw'], cfg['mot']])
        e.n.dsu.find(ek1); e.n.dsu.find(ek2)
        e.N = e.n.finalise(extra_edges=[(ek1, ek2, SHUNT_R, 'shunt',
                                         {'ref': sh, 'R': SHUNT_R})])
        e.rm = np.ones(len(e.n.A))

        def mk(e, cfg, phase_rms):
            def inj(ee):
                src = ee.n.node_at_pad(cfg['fet'], '9')
                snk = ee.n.node_at_pad(*cfg['conn'])
                return {src: phase_rms, snk: -phase_rms}
            return inj
        jobs.append(('Phase ' + cfg['tag'], e, mk(e, cfg, phase_rms)))
    return jobs


def main():
    print('=' * 80)
    print('Twin-GaN  PCB copper loss / temperature analysis')
    print('=' * 80)
    print(f"Scenario : {SCEN['vbat']:.0f} V in, {SCEN['i_dc_total']:.0f} A DC total, "
          f"{SCEN['i_dc_ch']:.0f} A per channel, {SCEN['tamb']:.0f} C ambient, "
          f"{SCEN['minutes']:.0f} min continuous")
    print(f"Stackup  : 1 oz (35 um) F.Cu/B.Cu, 0.5 oz (17.5 um) In1.Cu/In2.Cu")
    print(f"Copper   : F/B sheet R = {sheet_R('F.Cu')*1e3:.3f} mOhm/sq, "
          f"In1/In2 = {sheet_R('In1.Cu')*1e3:.3f} mOhm/sq, "
          f"0.3 mm via = {via_R(0.3)*1e3:.3f} mOhm")
    print(f"Phase    : {SCEN['phase_rms']:.2f} A rms per leg "
          f"(I_dc/(1.0607*m*cosphi), m=1, cosphi=1)")

    m = extract(load_board(BOARD))
    jobs = build_all(m, SCEN['phase_rms'])

    # ---- one combined thermal model over all power copper -----------------
    allnets = set()
    for cfg in PHASE_PATHS:
        allnets.add(cfg['sw']); allnets.add(cfg['mot'])
    allnets.update(['Vdrive', 'GND'])
    th = NetNetwork(m, allnets, h=H)
    extra = []
    for cfg in PHASE_PATHS:
        ek1, ek2 = ('pad', cfg['shunt'], '1'), ('pad', cfg['shunt'], '2')
        th.dsu.find(ek1); th.dsu.find(ek2)
        extra.append((ek1, ek2, 1.0 / SHUNT_G_TH, 'shunt', {'ref': cfg['shunt']}))
    Nth = th.finalise(extra_edges=vertical_edges(th) + extra)
    areas, lay_idx = node_area_layer(th)
    print(f"\nThermal model: {Nth} nodes, {len(th.A)} edges "
          f"({collections.Counter(th.kinds)})")

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
        Tvec = solve_thermal(th, Q, SCEN['tamb'], areas, lay_idx)
        Tlook = {k: Tvec[th.nid(k)] for k in th.dsu.p}
        print(f"  iteration {it+1}: copper dissipation {total*1000:8.1f} mW, "
              f"Tmax {Tvec.max():6.1f} C, board avg {Tvec.mean():5.1f} C")

    # ---- collect element rows -------------------------------------------
    rows = []

    def harvest(tag, e):
        n = e.n
        for i, (kind, (R0, meta)) in enumerate(zip(n.kinds, n.metas)):
            keys = (n.ek1[i], n.ek2[i])
            Te = max(Tlook.get(keys[0], 25.0), Tlook.get(keys[1], 25.0))
            I = abs(n.I[i]) * (2.0 if False else 1.0)
            rec = dict(tag=tag, kind=kind, layer='-', w=0.0, t=0.0,
                       I=I, P=e.P[i], T=Te, L=0.0, where='')
            if kind == 'zone':
                rec.update(layer=meta['layer'], w=n.h, t=T_LAYER[meta['layer']],
                           L=n.h,
                           where=f'pour cell ({meta["cell"][0]*n.h:.1f},{meta["cell"][1]*n.h:.1f})')
            elif kind == 'track':
                rec.update(layer=meta['layer'], w=meta['w'],
                           t=T_LAYER[meta['layer']], L=n._track_len(meta),
                           where=f'({meta["x1"]:.2f},{meta["y1"]:.2f})->({meta["x2"]:.2f},{meta["y2"]:.2f})')
            elif kind == 'via':
                v = meta['via']
                rec.update(layer=meta['layer'], w=math.pi * v['drill'],
                           t=25e-3,
                           where=f'{v["drill"]} mm via @({v["x"]:.2f},{v["y"]:.2f})')
            elif kind == 'shunt':
                rec.update(kind='shunt', layer='-', w=0, t=0,
                           where=f'shunt {meta.get("ref")} (2 mOhm)')
            else:
                continue
            rows.append(rec)

    per_job = {}
    for tag, e, inj in jobs:
        harvest(tag, e)
        per_job[tag] = e.P.sum()

    # ---- summary ---------------------------------------------------------
    print('\n' + '-' * 80)
    print('DISSIPATION BY BLOCK')
    print('-' * 80)
    print(f"  {'block':<12}{'P(mW)':>10}{'R_eff(mOhm)':>13}{'Tmax(C)':>10}")
    for tag, e, _ in jobs:
        Rs = e.P.sum() / (SCEN['phase_rms'] ** 2) if tag.startswith('Phase') \
            else e.P.sum() / (SCEN['i_dc_total'] ** 2)
        tmax = max(r['T'] for r in rows if r['tag'] == tag)
        print(f'  {tag:<12}{e.P.sum()*1000:10.2f}{Rs*1000:13.3f}{tmax:10.1f}')
    shunt_total = sum(r['P'] for r in rows if r['kind'] == 'shunt')
    P_total = sum(per_job.values())
    cu_total = P_total - shunt_total
    cu_rows = [r for r in rows if r['kind'] in ('track', 'zone', 'via')]
    print(f"  {'-'*43}")
    print(f"  {'PCB copper':<12}{cu_total*1000:10.1f}   <- what the copper itself burns")
    print(f"  {'Shunts':<12}{shunt_total*1000:10.1f}   <- component loss, not PCB copper")
    print(f"  {'TOTAL':<12}{P_total*1000:10.1f}")

    # ---- board thermal ---------------------------------------------------
    print('\n' + '-' * 80)
    print('TEMPERATURE')
    print('-' * 80)
    print(f"  Copper temperature range : {min(r['T'] for r in cu_rows):.1f} .. "
          f"{max(r['T'] for r in cu_rows):.1f} C")
    print(f"  Board-wide average       : {Tvec.mean():.1f} C  "
          f"(rise {Tvec.mean()-SCEN['tamb']:.1f} K)")

    def show(title, sel, n_show=10):
        rs = [r for r in rows if sel(r)]
        rs.sort(key=lambda r: r['T'], reverse=True)
        print(f"\n{title}")
        print(f"  {'T(C)':>7}{'dT(K)':>7}{'P(mW)':>9}{'I(A)':>7}{'w(mm)':>7}  "
              f"{'layer':<7} detail")
        for r in rs[:n_show]:
            print(f"  {r['T']:7.1f}{r['T']-SCEN['tamb']:7.1f}{r['P']*1000:9.3f}"
                  f"{r['I']:7.2f}{r['w']:7.2f}  {r['layer']:<7} {r['tag']} {r['where']}")
        return rs

    tr = show('HOTTEST DISCRETE TRACES', lambda r: r['kind'] == 'track')
    zr = show('HOTTEST COPPER POUR REGIONS', lambda r: r['kind'] == 'zone')
    vr = show('HOTTEST VIAS', lambda r: r['kind'] == 'via')
    sr = show('SHUNTS (component, not PCB copper)', lambda r: r['kind'] == 'shunt')
    pr = show('HIGHEST DISSIPATION ANYWHERE IN COPPER',
              lambda r: r['kind'] in ('track', 'zone', 'via'), 12)

    # ---- IPC cross-check -------------------------------------------------
    print('\n' + '-' * 80)
    print('IPC CROSS-CHECK ON THE 2.0 mm PHASE TRACES')
    print('-' * 80)
    print(f"  {'trace':<34}{'I(A)':>7}{'thermal-net':>12}{'IPC-2152':>10}{'IPC-2221':>10}")
    seen = set()
    for r in rows:
        if r['kind'] != 'track' or r['w'] < 1.5:
            continue
        key = (r['tag'], r['where'])
        if key in seen:
            continue
        seen.add(key)
        a = dt_ipc2152(r['I'], r['w'], r['t'], r['layer'])
        b = dt_ipc2221(r['I'], r['w'], r['t'], r['layer'])
        lbl = f"{r['tag']} {r['layer']} w={r['w']:.2f}"
        print(f"  {lbl:<34}{r['I']:7.2f}{r['T']:12.1f}{a:10.1f}{b:10.1f}")

    # ---- phase-current sensitivity ---------------------------------------
    print('\n' + '-' * 80)
    print('SENSITIVITY: PHASE CURRENT (DC input held at 20 A total)')
    print('-' * 80)
    print('  A 10 A DC channel only forces 9.43 A rms/phase at FULL modulation.')
    print('  At part throttle the phase current rises as 1/m, so this is the')
    print('  optimistic end of the operating envelope.')
    print(f"\n  {'I_phase(A)':>11}{'equiv m':>9}{'phase copper(mW)':>18}"
          f"{'2.0mm trace T(C)':>18}")
    base = max(r['T'] for r in rows if r['tag'] == 'Phase ch1-V' and r['kind'] == 'track')
    for iph in (9.43, 12.0, 15.0, 20.0):
        if abs(iph - SCEN['phase_rms']) < 1e-9:
            pcu = sum(per_job[t] for t in per_job if t.startswith('Phase')) - \
                  sum(r['P'] for r in rows if r['kind'] == 'shunt')
            tmax = base
            note = ' (solved)'
        else:
            # linear electrical + thermal network, with the ~9 % TCR correction
            # measured between the 20 C and converged full solve
            k = (iph / SCEN['phase_rms']) ** 2 * 1.09
            pcu = (sum(per_job[t] for t in per_job if t.startswith('Phase')) -
                   sum(r['P'] for r in rows if r['kind'] == 'shunt')) * k
            tmax = SCEN['tamb'] + (base - SCEN['tamb']) * k
            note = ''
        print(f"  {iph:>11.2f}{SCEN['i_dc_ch']/iph*0.943:>9.2f}{pcu*1000:>18.0f}{tmax:>18.1f}{note}")
    print('\n  IPC-2152 (KiCad\'s own formula) on a 2.0 mm x 1 oz external trace says')
    for iph in (9.43, 12.0, 15.0, 20.0):
        print(f"    {iph:5.2f} A -> dT = {dt_ipc2152(iph, 2.0, 0.035, 'F.Cu'):6.1f} K"
              f"  (T = {SCEN['tamb'] + dt_ipc2152(iph, 2.0, 0.035, 'F.Cu'):6.1f} C)")

    # ---- thermal time constant ------------------------------------------
    vol = 99e-3 * 99e-3 * 1.6e-3
    mass = vol * 1850
    C = mass * 1150
    tau = C * R_BOARD
    print('\n' + '-' * 80)
    print('10-MINUTE SOAK')
    print('-' * 80)
    print(f'  Bare FR4 thermal time constant ~ {tau:.0f} s ({tau/60:.1f} min)')
    print(f'  10 min = {SCEN["minutes"]*60/tau:.1f} time constants -> '
          f'{100*(1-math.exp(-SCEN["minutes"]*60/tau)):.1f} % of final rise')
    return rows, jobs, Tlook


if __name__ == '__main__':
    main()
