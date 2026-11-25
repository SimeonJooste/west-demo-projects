"""Convert the skid's CAD export (binary STL) into the compact skid.json the site loads.

Usage:
    python3 tools/stl_to_web.py path/to/model.STL skid.json [--html index.html]

What it does:
  1. Reads the binary STL and merges duplicate vertices.
  2. Splits the mesh into its separate parts (connected pieces).
  3. Simplifies each part on its own, so small fasteners are reduced hard while
     large, detailed parts (grilles, the fan unit) keep their shape.
  4. Writes positions as 16-bit values inside the model's bounding box and indices as
     16-bit values per chunk, then base64-encodes it into JSON (a file type every host serves).

With --html, it also updates the EXPECTED file size the page uses for its loading bar.
It prints the model's bounding box so you can update the dimensions on the page if a new
revision changes them.

Requires: numpy, scipy, fast-simplification (pip install -r tools/requirements.txt)
"""
import argparse, base64, json, os, re, struct, sys, time

import numpy as np
import fast_simplification
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

# Simplification budget per part: keep at least FLOOR triangles, at least SHARE of the
# original, and at least AREA_DENSITY triangles per square metre of the part's bounding-box
# surface. Large detailed parts (> BIG_AREA m2 and > BIG_TRIS triangles) keep BIG_SHARE.
FLOOR, SHARE, AREA_DENSITY = 80, 0.08, 5000
BIG_AREA, BIG_TRIS, BIG_SHARE = 0.5, 10000, 0.5


def read_stl(path):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.read(80)
        n = struct.unpack("<I", fh.read(4))[0]
    if 84 + 50 * n != size:
        sys.exit("This looks like an ASCII STL or a damaged file; export it as binary STL.")
    dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
    tris = np.fromfile(path, dtype=dt, offset=84)["v"].reshape(-1, 3)
    verts, inv = np.unique(tris, axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3)
    ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return verts.astype(np.float32), faces[ok].astype(np.int64), n


def simplify_by_part(V, F):
    n = len(V)
    rows = np.concatenate([F[:, 0], F[:, 1]])
    cols = np.concatenate([F[:, 1], F[:, 2]])
    graph = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n))
    k, label = connected_components(graph, directed=False)
    flab = label[F[:, 0]]
    order = np.argsort(flab, kind="stable")
    Fs, fls = F[order], flab[order]
    starts = np.searchsorted(fls, np.arange(k + 1))
    outV, outF, base = [], [], 0
    for c in range(k):
        f = Fs[starts[c]:starts[c + 1]]
        if len(f) == 0:
            continue
        used, inv = np.unique(f.ravel(), return_inverse=True)
        v, ff = V[used], inv.reshape(-1, 3)
        size_m = (v.max(0) - v.min(0)) / 1000.0
        area = size_m[0] * size_m[1] + size_m[1] * size_m[2] + size_m[0] * size_m[2]
        target = min(len(f), int(max(FLOOR, SHARE * len(f), AREA_DENSITY * area)))
        if area > BIG_AREA and len(f) > BIG_TRIS:
            target = int(len(f) * BIG_SHARE)
        if target < len(f):
            v2, f2 = fast_simplification.simplify(v, ff, target_reduction=1 - target / len(f), agg=7)
            if len(f2) == 0:
                v2, f2 = v, ff
        else:
            v2, f2 = v, ff
        outV.append(v2.astype(np.float32))
        outF.append(f2.astype(np.int64) + base)
        base += len(v2)
    return np.concatenate(outV), np.concatenate(outF), k


def pack(v, f):
    """SKD2: 'SKD2', vertex count, chunk count, bbox min/max (float32),
    chunk table (vertex start, vertex count, triangle count), uint16 positions, uint16 local indices."""
    used = np.unique(f)
    remap = -np.ones(len(v), np.int64)
    remap[used] = np.arange(len(used))
    v, f = v[used], remap[f]
    mn, mx = v.min(0), v.max(0)
    q = np.round((v - mn) / (mx - mn) * 65535).astype("<u2")
    fmin, fmax = f.min(1), f.max(1)
    chunks, start, lo, hi = [], 0, int(fmin[0]), int(fmax[0])
    for i in range(1, len(f)):
        nlo, nhi = min(lo, int(fmin[i])), max(hi, int(fmax[i]))
        if nhi - nlo + 1 > 65535:
            chunks.append((start, i, lo, hi))
            start, lo, hi = i, int(fmin[i]), int(fmax[i])
        else:
            lo, hi = nlo, nhi
    chunks.append((start, len(f), lo, hi))
    table, idx = b"", b""
    for a, b, vs, ve in chunks:
        table += struct.pack("<III", vs, ve - vs + 1, b - a)
        idx += (f[a:b] - vs).astype("<u2").tobytes()
    head = b"SKD2" + struct.pack("<II", len(v), len(chunks)) + np.array([*mn, *mx], "<f4").tobytes()
    return head + table + q.tobytes() + idx, len(v), len(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stl")
    ap.add_argument("out", nargs="?", default="skid.json")
    ap.add_argument("--html", help="update the EXPECTED size constant in this page")
    a = ap.parse_args()

    t = time.time()
    V, F, n_in = read_stl(a.stl)
    size = V.max(0) - V.min(0)
    print(f"Read {n_in:,} triangles; bounding box X {size[0]:.1f} x Y {size[1]:.1f} x Z {size[2]:.1f} (STL units)")
    V2, F2, parts = simplify_by_part(V, F)
    blob, nv, nt = pack(V2, F2)
    note = os.path.splitext(os.path.basename(a.stl))[0] + ", simplified for web"
    with open(a.out, "w") as fh:
        json.dump({"format": "SKD2", "note": note, "b64": base64.b64encode(blob).decode()}, fh)
    out_size = os.path.getsize(a.out)
    print(f"{parts:,} parts -> {nt:,} triangles, {nv:,} vertices; wrote {a.out} ({out_size:,} bytes) in {time.time() - t:.0f}s")

    if a.html:
        page = open(a.html).read()
        page, count = re.subn(r"const EXPECTED=\d+;", f"const EXPECTED={out_size};", page)
        if count != 1:
            sys.exit("Could not find the EXPECTED constant in the page.")
        open(a.html, "w").write(page)
        print(f"Updated EXPECTED in {a.html} to {out_size:,}")


if __name__ == "__main__":
    main()
