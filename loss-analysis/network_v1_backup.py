"""3-D resistive network model of PCB copper, solved with conjugate gradient.

Nodes: zone mesh cells, track endpoints, via barrels, pads.
Edges: sheet resistance between mesh cells, track resistance, via barrel
resistance, pad contacts, and explicit component resistors (shunts).

Stackup modelled as built: 1 oz (35 um) F.Cu / B.Cu,
0.5 oz (17.5 um) In1.Cu / In2.Cu.  Copper resistivity is temperature
dependent; the caller iterates the electro-thermal loop.
"""
import math
import numpy as np

RHO20 = 1.72e-8          # ohm.m
ALPHA_CU = 0.00393       # 1/K
T_LAYER = {'F.Cu': 0.035, 'B.Cu': 0.035,
           'In1.Cu': 0.0175, 'In2.Cu': 0.0175}
LAYER_Z = {'F.Cu': 0.0175, 'In1.Cu': 0.1525, 'In2.Cu': 1.419, 'B.Cu': 1.545}
LAYER_ORDER = ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
COPPER_LAYERS = set(T_LAYER)
H = 0.5                  # mesh pitch, mm
VIA_PLATING = 25e-6      # m, finished barrel plating


def rho_cu(temp_c=20.0):
    return RHO20 * (1 + ALPHA_CU * (temp_c - 20.0))


def sheet_R(layer, temp_c=20.0):
    """Ohms per square."""
    return rho_cu(temp_c) / (T_LAYER[layer] * 1e-3)


def via_R(drill_mm, temp_c=20.0):
    """Total barrel resistance F.Cu -> B.Cu."""
    length = (LAYER_Z['B.Cu'] - LAYER_Z['F.Cu']) * 1e-3
    area = math.pi * (drill_mm * 1e-3) * VIA_PLATING
    return rho_cu(temp_c) * length / area


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        r = x
        while self.p[r] != r:
            r = self.p[r]
        while self.p[x] != r:
            self.p[x], x = r, self.p[x]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def fill_poly(pts, h=None):
    """Cells touched by a simple polygon: scanline interior + boundary."""
    if h is None:
        h = H
    cells = set()
    n = len(pts)
    if n < 3:
        return cells
    ys = [p[1] for p in pts]
    iy0 = int(math.floor(min(ys) / h)) - 1
    iy1 = int(math.ceil(max(ys) / h)) + 1
    for iy in range(iy0, iy1 + 1):
        yc = (iy + 0.5) * h
        xs = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if y1 == y2:
                continue
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                t = (yc - y1) / (y2 - y1)
                xs.append(x1 + t * (x2 - x1))
        if len(xs) < 2:
            continue
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            a, b = xs[k], xs[k + 1]
            ia = int(math.ceil(a / h - 0.5))
            ib = int(math.floor(b / h - 0.5))
            for ix in range(ia, ib + 1):
                cells.add((ix, iy))
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        d = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(d / (h * 0.5)) + 1)
        for s in range(steps + 1):
            t = s / steps
            cells.add((int(math.floor((x1 + (x2 - x1) * t) / h)),
                       int(math.floor((y1 + (y2 - y1) * t) / h))))
    return cells


def xf(fx, fy, rot, px, py):
    """KiCad footprint-local -> board transform (validated against traces)."""
    th = math.radians(rot)
    c, s = math.cos(th), math.sin(th)
    return (fx + px * c + py * s, fy - px * s + py * c)


def pad_local(p, x, y):
    """Board point -> pad-local coordinates, measured from the pad centre."""
    th = math.radians(p['fp_rot'])
    c, s = math.cos(th), math.sin(th)
    u, v = x - p['fp_x'], y - p['fp_y']
    px, py = u * c - v * s, u * s + v * c
    dx, dy = px - p['x'], py - p['y']          # offset from pad centre
    pr = math.radians(p.get('rot') or 0.0)
    cp, sp = math.cos(-pr), math.sin(-pr)
    return dx * cp - dy * sp, dx * sp + dy * cp


class NetNetwork:
    def __init__(self, model, nets, temp_c=20.0, h=H):
        self.m = model
        self.nets = set(nets)
        self.temp = temp_c
        self.h = h
        self.dsu = DSU()
        self.cells = {}
        self.edges = []
        self.via_pos = {}
        self.pad_key = {}
        self.pt_keys = []
        self._vid = 0
        self._build()

    # ---------- construction ----------
    def _build(self):
        m = self.m
        nets = self.nets

        for z in m['zones']:
            if z['net'] not in nets:
                continue
            for fp in z['filled']:
                lay = fp['layer']
                if lay not in COPPER_LAYERS:
                    continue
                self.cells.setdefault(lay, set()).update(fill_poly(fp['pts'], self.h))

        for lay, cs in self.cells.items():
            for c in cs:
                self.dsu.find(('cell', lay, c[0], c[1]))

        # sheet-resistance mesh between adjacent occupied cells (one square each)
        for lay, cs in self.cells.items():
            Rs = sheet_R(lay, self.temp)
            for (ix, iy) in cs:
                k = ('cell', lay, ix, iy)
                if (ix + 1, iy) in cs:
                    self.edges.append((k, ('cell', lay, ix + 1, iy), Rs, 'zone',
                                       {'layer': lay, 'cell': (ix, iy), 'dir': 'x'}))
                if (ix, iy + 1) in cs:
                    self.edges.append((k, ('cell', lay, ix, iy + 1), Rs, 'zone',
                                       {'layer': lay, 'cell': (ix, iy), 'dir': 'y'}))

        for t in m['tracks']:
            if t['net'] not in nets:
                continue
            k1 = self._ptkey(t['layer'], t['x1'], t['y1'])
            k2 = self._ptkey(t['layer'], t['x2'], t['y2'])
            R = sheet_R(t['layer'], self.temp) * self._track_len(t) / t['w']
            self.edges.append((k1, k2, R, 'track', t))
            self._bind_to_zone(k1)
            self._bind_to_zone(k2)

        for v in m['vias']:
            if v['net'] not in nets:
                continue
            self._add_via(v)

        for p in m['pads']:
            if p['net'] not in nets or p['x'] is None:
                continue
            self._add_pad(p)

    def _track_len(self, t):
        d = math.hypot(t['x2'] - t['x1'], t['y2'] - t['y1'])
        if t.get('arc') and t.get('mx') is not None:
            ax, ay = t['x1'], t['y1']
            bx, by = t['mx'], t['my']
            cx, cy = t['x2'], t['y2']
            d1 = math.hypot(bx - ax, by - ay)
            d2 = math.hypot(cx - bx, cy - by)
            d3 = math.hypot(cx - ax, cy - ay)
            area = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
            if area < 1e-9:
                return d3
            Rr = d1 * d2 * d3 / (4 * area)
            return Rr * 2 * math.asin(min(1.0, d3 / (2 * Rr)))
        return d

    def _ptkey(self, layer, x, y):
        k = ('pt', layer, round(x, 4), round(y, 4))
        if k not in self.dsu.p:
            self.pt_keys.append(k)
        self.dsu.find(k)
        return k

    def _bind_to_zone(self, key):
        _, layer, x, y = key
        c = (int(math.floor(x / self.h)), int(math.floor(y / self.h)))
        if c in self.cells.get(layer, ()):
            self.dsu.union(key, ('cell', layer, c[0], c[1]))

    def _add_via(self, v):
        lay = LAYER_ORDER
        if v['layers'] and len(v['layers']) >= 2:
            try:
                a = LAYER_ORDER.index(v['layers'][0])
                b = LAYER_ORDER.index(v['layers'][-1])
                lay = LAYER_ORDER[a:b + 1]
            except ValueError:
                lay = LAYER_ORDER
        vid = self._vid
        self._vid += 1
        self.via_pos[vid] = (v['x'], v['y'])
        Rtot = via_R(v['drill'], self.temp)
        zs = [LAYER_Z[l] for l in lay]
        keys = []
        for l in lay:
            k = ('via', vid, l)
            keys.append(k)
            self.dsu.find(k)
            c = (int(math.floor(v['x'] / self.h)), int(math.floor(v['y'] / self.h)))
            if c in self.cells.get(l, ()):
                self.dsu.union(k, ('cell', l, c[0], c[1]))
        total_z = zs[-1] - zs[0]
        for i in range(len(lay) - 1):
            frac = (zs[i + 1] - zs[i]) / total_z if total_z else 0.0
            self.edges.append((keys[i], keys[i + 1], Rtot * frac,
                               'via', {'via': v, 'layer': lay[i]}))

    def _add_pad(self, p):
        k = ('pad', p['ref'], p['num'])
        self.dsu.find(k)
        self.pad_key[(p['ref'], p['num'])] = k
        layers = [p['fp_layer']] if p['type'] == 'smd' else list(LAYER_ORDER)
        layers = [l for l in layers if l in COPPER_LAYERS]
        hw = (p['w'] or 0) / 2
        hh = (p['h'] or 0) / 2

        for lay in layers:
            cs = self.cells.get(lay)
            if not cs:
                continue
            cx, cy = xf(p['fp_x'], p['fp_y'], p['fp_rot'], p['x'], p['y'])
            ix0 = int(math.floor((cx - hw - 0.5) / self.h)) - 1
            ix1 = int(math.ceil((cx + hw + 0.5) / self.h)) + 1
            iy0 = int(math.floor((cy - hh - 0.5) / self.h)) - 1
            iy1 = int(math.ceil((cy + hh + 0.5) / self.h)) + 1
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    if (ix, iy) not in cs:
                        continue
                    gx, gy = (ix + 0.5) * self.h, (iy + 0.5) * self.h
                    lx, ly = pad_local(p, gx, gy)
                    if abs(lx) <= hw + 1e-9 and abs(ly) <= hh + 1e-9:
                        self.dsu.union(k, ('cell', lay, ix, iy))
        # bind coincident track endpoints / vias lying inside the pad
        for kk in self.pt_keys:
            _, lay, x, y = kk
            if lay not in layers:
                continue
            lx, ly = pad_local(p, x, y)
            if abs(lx) <= hw + 1e-9 and abs(ly) <= hh + 1e-9:
                self.dsu.union(k, kk)
        for vid, (vx, vy) in self.via_pos.items():
            lx, ly = pad_local(p, vx, vy)
            if abs(lx) <= hw + 1e-9 and abs(ly) <= hh + 1e-9:
                self.dsu.union(k, ('via', vid, LAYER_ORDER[0]))
                self.dsu.union(k, ('via', vid, LAYER_ORDER[-1]))

    # ---------- finalise ----------
    def finalise(self, extra_edges=()):
        remap = {}
        for k in list(self.dsu.p):
            r = self.dsu.find(k)
            remap.setdefault(r, len(remap))
        self.node_of = remap
        n = len(remap)

        def nid(k):
            return remap[self.dsu.find(k)]

        self.nid = nid
        ea, eb, eg, kinds, metas = [], [], [], [], []
        for (k1, k2, R, kind, meta) in list(self.edges) + list(extra_edges):
            if R <= 0:
                continue
            a, b = nid(k1), nid(k2)
            if a == b:
                continue
            ea.append(a)
            eb.append(b)
            eg.append(1.0 / R)
            kinds.append(kind)
            metas.append((R, meta))
        self.A = np.array(ea, dtype=np.int64)
        self.B = np.array(eb, dtype=np.int64)
        self.G = np.array(eg, dtype=np.float64)
        self.kinds = kinds
        self.metas = metas
        self.n = n
        return n

    def node_at_pad(self, ref, num):
        return self.nid(self.pad_key[(ref, num)])

    def node_near(self, x, y, layer=None):
        best = (1e9, None)
        for k in self.dsu.p:
            if k[0] == 'pt':
                _, l, kx, ky = k
                if layer and l != layer:
                    continue
                d = math.hypot(kx - x, ky - y)
            elif k[0] == 'via':
                _, vid, l = k
                if layer and l != layer:
                    continue
                d = math.hypot(self.via_pos[vid][0] - x, self.via_pos[vid][1] - y)
            elif k[0] == 'pad':
                continue
            else:
                _, l, ix, iy = k
                if layer and l != layer:
                    continue
                d = math.hypot((ix + 0.5) * self.h - x, (iy + 0.5) * self.h - y)
            if d < best[0]:
                best = (d, k)
        return self.nid(best[1]), best[0]

    # ---------- solve ----------
    def solve(self, injections, iters=60000, tol=1e-12, verbose=True):
        n = self.n
        rhs = np.zeros(n)
        for k, v in injections.items():
            rhs[k] += v
        rhs -= rhs.mean()
        A, B, G = self.A, self.B, self.G

        def matvec(v):
            f = G * (v[A] - v[B])
            return np.bincount(A, weights=f, minlength=n) - np.bincount(B, weights=f, minlength=n)

        x = np.zeros(n)
        r = rhs.copy()
        p = r.copy()
        rs = float(r @ r)
        rs0 = rs if rs > 0 else 1.0
        used = 0
        for it in range(iters):
            Ap = matvec(p)
            pAp = float(p @ Ap)
            if pAp <= 0:
                break
            al = rs / pAp
            x += al * p
            r -= al * Ap
            rsn = float(r @ r)
            used = it
            if rsn < tol * rs0 or rsn < 1e-26:
                break
            p = r + (rsn / rs) * p
            rs = rsn
        else:
            used = iters
        if verbose:
            print(f'    CG iters={used} relres={rs/rs0:.2e} nodes={n} edges={len(G)}')
        self.v = x
        self.I = G * (x[A] - x[B])
        self.P = self.I ** 2 / G
        return x

    def total_power(self):
        return float(self.P.sum())

    def effective_resistance(self, ia, ib, current):
        """R between two nodes given the solved drop and driven current."""
        return abs(self.v[ia] - self.v[ib]) / current


# --------------------------------------------------------------------------
# Thermal side: same copper topology, conduction instead of resistance.
# --------------------------------------------------------------------------
K_CU = 385.0      # W/m.K
K_FR4 = 0.3       # W/m.K
H_SURF = 12.0     # W/m2K, natural convection + radiation from an outer face
H_INNER = 20.0    # W/m2K, inner copper -> ambient via FR4 + surface


def thermal_conductance(net, shunt_G=0.05):
    """Per-edge thermal conductance [W/K] on the finalised electrical topology."""
    Gth = np.zeros(len(net.A))
    for i, (kind, (R, meta)) in enumerate(zip(net.kinds, net.metas)):
        if kind == 'zone':
            lay = meta['layer']
            Gth[i] = K_CU * T_LAYER[lay] * 1e-3           # k*t per square
        elif kind == 'track':
            t = meta
            L = net._track_len(t)
            if L > 0:
                Gth[i] = K_CU * T_LAYER[t['layer']] * 1e-3 * t['w'] / L
        elif kind == 'via':
            v = meta['via']
            ab = math.pi * (v['drill'] * 1e-3) * VIA_PLATING
            seg = abs(LAYER_Z[meta['layer']] - LAYER_Z[LAYER_ORDER[LAYER_ORDER.index(meta['layer']) + 1]]) * 1e-3
            Gth[i] = K_CU * ab / seg if seg > 0 else 0.1
        else:
            Gth[i] = shunt_G
    return Gth


def node_geometry(net):
    """Per final node: representative layer index and copper area [m2]."""
    import collections as _c
    n = net.n
    areas = np.zeros(n)
    layers = _c.defaultdict(set)
    for k in net.dsu.p:
        nid = net.nid(k)
        if k[0] == 'cell':
            _, lay, ix, iy = k
            areas[nid] += (net.h * 1e-3) ** 2
            layers[nid].add(lay)
        elif k[0] == 'pt':
            layers[nid].add(k[1])
        elif k[0] == 'via':
            layers[nid].add(k[2])
    # pads contribute their own footprint area
    for (ref, num), k in net.pad_key.items():
        nid = net.nid(k)
        p = next((q for q in net.m['pads'] if q['ref'] == ref and q['num'] == num), None)
        if p and p['w'] and p['h']:
            areas[nid] += p['w'] * 1e-3 * p['h'] * 1e-3
            layers[nid].add(p['fp_layer'])
    lay_idx = np.full(n, -1, dtype=int)
    for nid, ls in layers.items():
        if ls:
            lay_idx[nid] = min(LAYER_ORDER.index(l) for l in ls if l in LAYER_ORDER)
    return areas, lay_idx


def solve_thermal(net, Q, Tref, areas, lay_idx, iters=60000, tol=1e-12):
    """Q: heat [W] injected per node. Returns node temperatures [C]."""
    n = net.n
    Gth = thermal_conductance(net)
    h = np.where(lay_idx == 0, H_SURF, np.where(lay_idx == 3, H_SURF, H_INNER))
    Gamb = h * areas
    # add ambient edges as extra conductance to a reference handled on the RHS
    rhs = Q + Gamb * Tref
    A, B = net.A, net.B

    def matvec(v):
        f = Gth * (v[A] - v[B])
        y = np.bincount(A, weights=f, minlength=n) - np.bincount(B, weights=f, minlength=n)
        y += Gamb * v
        return y

    x = np.full(n, Tref)
    r = rhs - matvec(x)
    p = r.copy()
    rs = float(r @ r)
    rs0 = rs if rs > 0 else 1.0
    for it in range(iters):
        Ap = matvec(p)
        pAp = float(p @ Ap)
        if pAp <= 0:
            break
        al = rs / pAp
        x += al * p
        r -= al * Ap
        rn = float(r @ r)
        if rn < tol * rs0:
            break
        p = r + (rn / rs) * p
        rs = rn
    return x
