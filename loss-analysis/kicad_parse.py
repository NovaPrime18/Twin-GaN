"""Minimal KiCad 10 s-expression parser + board model extractor.

Produces a structured model of the PCB copper: tracks, vias, zones,
footprint pads -- everything needed for a resistive loss / thermal analysis.
"""
import math
import re


def tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in ' \t\r\n':
            i += 1
            continue
        if c == '(' or c == ')':
            toks.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == '\\' and j + 1 < n:
                    buf.append(src[j + 1])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            toks.append(('STR', ''.join(buf)))
            i = j + 1
            continue
        j = i
        while j < n and src[j] not in ' \t\r\n()"':
            j += 1
        toks.append(('ATOM', src[i:j]))
        i = j
    return toks


def parse(src):
    toks = tokenize(src)
    pos = 0

    def rd():
        nonlocal pos
        t = toks[pos]
        if t == '(':
            pos += 1
            lst = []
            while toks[pos] != ')':
                lst.append(rd())
            pos += 1
            return lst
        pos += 1
        return t[1]

    out = []
    while pos < len(toks):
        out.append(rd())
    return out


def is_list(x):
    return isinstance(x, list)


def find_all(node, key):
    """Direct children lists whose head is key."""
    res = []
    if not is_list(node):
        return res
    for ch in node:
        if is_list(ch) and ch and ch[0] == key:
            res.append(ch)
    return res


def find_one(node, key):
    r = find_all(node, key)
    return r[0] if r else None


def nums(node):
    out = []
    for ch in node[1:]:
        if is_list(ch):
            continue
        try:
            out.append(float(ch))
        except (TypeError, ValueError):
            pass
    return out


def load_board(path):
    src = open(path, encoding='utf-8').read()
    tree = parse(src)
    board = None
    for t in tree:
        if is_list(t) and t and t[0] == 'kicad_pcb':
            board = t
            break
    if board is None:
        raise SystemExit('no kicad_pcb root found')
    return board


def extract(board):
    m = {
        'tracks': [],   # dicts
        'vias': [],
        'zones': [],
        'pads': [],
        'footprints': [],
        'nets': set(),
        'stackup': [],
    }

    # --- stackup copper thickness ---
    setup = find_one(board, 'setup')
    if setup:
        su = find_one(setup, 'stackup')
        if su:
            for lay in find_all(su, 'layer'):
                name = lay[1] if len(lay) > 1 else '?'
                typ = find_one(lay, 'type')
                th = find_one(lay, 'thickness')
                m['stackup'].append({
                    'name': name,
                    'type': typ[1] if typ else None,
                    'thickness': float(th[1]) if th else None,
                })

    def net_of(node):
        n = find_one(node, 'net')
        if n is None:
            return None
        return n[1] if len(n) > 1 else None

    # --- tracks ---
    for seg in find_all(board, 'segment'):
        s = find_one(seg, 'start')
        e = find_one(seg, 'end')
        w = find_one(seg, 'width')
        l = find_one(seg, 'layer')
        net = net_of(seg)
        m['nets'].add(net)
        m['tracks'].append({
            'x1': float(s[1]), 'y1': float(s[2]),
            'x2': float(e[1]), 'y2': float(e[2]),
            'w': float(w[1]), 'layer': l[1], 'net': net,
        })

    # --- arcs (curved tracks) ---
    for arc in find_all(board, 'arc'):
        s = find_one(arc, 'start')
        mid = find_one(arc, 'mid')
        e = find_one(arc, 'end')
        w = find_one(arc, 'width')
        l = find_one(arc, 'layer')
        net = net_of(arc)
        if not (s and e and w and l):
            continue
        m['nets'].add(net)
        m['tracks'].append({
            'x1': float(s[1]), 'y1': float(s[2]),
            'x2': float(e[1]), 'y2': float(e[2]),
            'mx': float(mid[1]) if mid else None,
            'my': float(mid[2]) if mid else None,
            'w': float(w[1]), 'layer': l[1], 'net': net,
            'arc': True,
        })

    # --- vias ---
    for v in find_all(board, 'via'):
        at = find_one(v, 'at')
        size = find_one(v, 'size')
        drill = find_one(v, 'drill')
        layers = find_one(v, 'layers')
        net = net_of(v)
        m['nets'].add(net)
        m['vias'].append({
            'x': float(at[1]), 'y': float(at[2]),
            'size': float(size[1]) if size else None,
            'drill': float(drill[1]) if drill else None,
            'layers': [x for x in layers[1:] if not is_list(x)] if layers else [],
            'net': net,
        })

    # --- zones ---
    for z in find_all(board, 'zone'):
        net = find_one(z, 'net')
        lay = find_one(z, 'layer')
        netname = net[1] if net else None
        m['nets'].add(netname)
        if lay:
            layers = [lay[1]]
        else:
            laynode = find_one(z, 'layers')
            layers = [x for x in laynode[1:] if not is_list(x)] if laynode else []
        prio = find_one(z, 'priority')
        polys = []
        # filled geometry: filled_polygon -> pts -> xy
        for fp in find_all(z, 'filled_polygon'):
            fl = find_one(fp, 'layer')
            pts = []
            for pts_node in find_all(fp, 'pts'):
                for xy in find_all(pts_node, 'xy'):
                    pts.append((float(xy[1]), float(xy[2])))
            if len(pts) >= 3:
                polys.append({'layer': fl[1] if fl else (layers[0] if layers else None),
                              'pts': pts})
        outline = []
        poly = find_one(z, 'polygon')
        if poly:
            for pts_node in find_all(poly, 'pts'):
                for xy in find_all(pts_node, 'xy'):
                    outline.append((float(xy[1]), float(xy[2])))
        m['zones'].append({
            'net': netname,
            'layers': layers,
            'priority': int(float(prio[1])) if prio else 0,
            'outline': outline,
            'filled': polys,
        })

    # --- footprints + pads ---
    for fp in find_all(board, 'footprint'):
        at = find_one(fp, 'at')
        props = {}
        for p in find_all(fp, 'property'):
            if len(p) >= 3:
                props[p[1]] = p[2]
        ref = props.get('Reference')
        f = {
            'ref': ref,
            'value': props.get('Value'),
            'x': float(at[1]) if at else None,
            'y': float(at[2]) if at else None,
            'rot': float(at[3]) if at and len(at) > 3 else 0.0,
            'layer': find_one(fp, 'layer')[1] if find_one(fp, 'layer') else 'F.Cu',
            'pads': [],
        }
        for pad in find_all(fp, 'pad'):
            if not is_list(pad) or len(pad) < 3:
                continue
            num = pad[1]
            ptype = pad[2]
            pshape = pad[3] if len(pad) > 3 else None
            pat = find_one(pad, 'at')
            psz = find_one(pad, 'size')
            pnet = find_one(pad, 'net')
            layers = find_one(pad, 'layers')
            padrec = {
                'ref': ref, 'num': num, 'type': ptype, 'shape': pshape,
                'x': float(pat[1]) if pat else None,
                'y': float(pat[2]) if pat else None,
                'rot': float(pat[3]) if pat and len(pat) > 3 else 0.0,
                'w': float(psz[1]) if psz else None,
                'h': float(psz[2]) if psz and len(psz) > 2 else None,
                'net': pnet[1] if pnet else None,
                'layers': [x for x in layers[1:] if not is_list(x)] if layers else [],
                'fp_layer': f['layer'],
                'fp_rot': f['rot'],
                'fp_x': f['x'], 'fp_y': f['y'],
            }
            f['pads'].append(padrec)
            m['pads'].append(padrec)
        m['footprints'].append(f)

    return m


if __name__ == '__main__':
    import sys
    b = load_board(sys.argv[1] if len(sys.argv) > 1 else
                   '/home/tj/Twin-GaN/Twin-GaN-VESC.kicad_pcb')
    m = extract(b)
    print('tracks', len(m['tracks']))
    print('vias', len(m['vias']))
    print('zones', len(m['zones']))
    print('pads', len(m['pads']))
    print('footprints', len(m['footprints']))
    print('nets', len(m['nets']))
    print('stackup:')
    for s in m['stackup']:
        print('  ', s)
