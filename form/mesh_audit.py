#!/usr/bin/env python3
"""Limited, non-repairing STL screen. Assumes mm. See docs/VALIDATION.md."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

LIMITS = [
    'STL units assumed to be mm; external scale verification required.',
    'No general self-intersection, vertex-manifold, wall-thickness or strength proof.',
    'No shell nesting interpretation; cavity shells may require a kernel-aware review.',
    'Envelope check allows translation, not rotation, packing, supports or brim geometry.',
]

def read_stl(path):
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from('<I', data, 80)[0]
        if len(data) == 84 + 50 * count:
            triangles = []
            for i in range(count):
                values = struct.unpack_from('<12fH', data, 84 + i * 50)
                triangles.append(tuple(tuple(values[j:j+3]) for j in (3, 6, 9)))
            return triangles, 'binary', hashlib.sha256(data).hexdigest()
    try:
        lines = data.decode('ascii').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError('Not a recognized binary or ASCII STL; possible truncation.') from exc
    if not lines or not lines[0].strip().lower().startswith('solid'):
        raise ValueError('ASCII STL must begin with solid; binary size may be invalid.')
    vertices = []
    facets = 0
    ends = 0
    for line in lines:
        fields = line.strip().split()
        if not fields:
            continue
        if fields[0].lower() == 'vertex':
            if len(fields) != 4:
                raise ValueError('Malformed vertex record.')
            vertices.append(tuple(float(v) for v in fields[1:]))
        elif fields[0].lower() == 'facet':
            facets += 1
        elif fields[0].lower() == 'endfacet':
            ends += 1
    if len(vertices) % 3 or facets != len(vertices) // 3 or facets != ends:
        raise ValueError('Inconsistent ASCII facet/vertex counts.')
    if not any(line.strip().lower().startswith('endsolid') for line in lines):
        raise ValueError('Missing ASCII endsolid.')
    triangles = [tuple(vertices[i:i+3]) for i in range(0, len(vertices), 3)]
    return triangles, 'ascii', hashlib.sha256(data).hexdigest()

def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))

def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

def dot(a, b):
    return sum(x*y for x, y in zip(a, b))

def audit(triangles, bed=(180, 180, 180), margin=5.0, expected_components=1,
          expected_size=None, dimension_tolerance=0.05, weld_grid=1e-6):
    values = list(bed) + [margin, dimension_tolerance, weld_grid]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Settings must be finite.')
    if min(bed) <= 0 or margin < 0 or 2*margin >= min(bed[:2]):
        raise ValueError('Invalid build envelope or XY margin.')
    if weld_grid <= 0 or dimension_tolerance < 0 or expected_components < 1:
        raise ValueError('Invalid tolerance, grid or component count.')
    if expected_size is not None and (len(expected_size) != 3 or
            not all(math.isfinite(v) and v > 0 for v in expected_size)):
        raise ValueError('Expected dimensions must be three finite positive values.')
    failures = []
    result = {'units': 'mm (assumed)', 'triangles': len(triangles),
              'weld_grid_mm': weld_grid, 'limitations': LIMITS,
              'failures': failures, 'status': 'FAIL'}
    if not triangles:
        failures.append('empty_mesh')
        return result
    if any(len(t) != 3 or any(len(v) != 3 for v in t) for t in triangles):
        raise ValueError('Each triangle must have three XYZ vertices.')
    vertices = [v for t in triangles for v in t]
    if not all(math.isfinite(c) for v in vertices for c in v):
        failures.append('nonfinite_coordinates')
        return result
    lo = [min(v[i] for v in vertices) for i in range(3)]
    hi = [max(v[i] for v in vertices) for i in range(3)]
    size = [b-a for a, b in zip(lo, hi)]
    origin = [(a+b)/2 for a, b in zip(lo, hi)]
    available = [bed[0]-2*margin, bed[1]-2*margin, bed[2]]
    fits = all(s <= a + 1e-6 for s, a in zip(size, available))
    result.update(bounds_mm=[lo, hi], size_mm=size, usable_envelope_mm=available,
                  fits_centered_axis_aligned=fits)
    if not fits:
        failures.append('exceeds_axis_aligned_envelope')
    if expected_size is not None:
        errors = [abs(a-b) for a, b in zip(size, expected_size)]
        result['dimension_errors_mm'] = errors
        if any(e > dimension_tolerance for e in errors):
            failures.append('unexpected_dimensions')
    edges = defaultdict(list)
    seen_faces = set()
    degenerate = duplicate = 0
    parent = list(range(len(triangles)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a, b):
        a, b = root(a), root(b)
        if a != b:
            parent[b] = a
    for i, t in enumerate(triangles):
        keys = [tuple(round(c / weld_grid) for c in v) for v in t]
        norm2 = dot(cross(sub(t[1], t[0]), sub(t[2], t[0])),
                    cross(sub(t[1], t[0]), sub(t[2], t[0])))
        if len(set(keys)) != 3 or norm2 <= weld_grid**4:
            degenerate += 1
        face = tuple(sorted(keys))
        duplicate += int(face in seen_faces)
        seen_faces.add(face)
        for a, b in zip(keys, keys[1:] + keys[:1]):
            edge = tuple(sorted((a, b)))
            edges[edge].append((i, 1 if a < b else -1))
    boundary = nonmanifold = winding = 0
    for entries in edges.values():
        boundary += int(len(entries) == 1)
        nonmanifold += int(len(entries) > 2)
        winding += int(len(entries) == 2 and entries[0][1] == entries[1][1])
        for item in entries[1:]:
            union(entries[0][0], item[0])
    volumes = defaultdict(float)
    for i, t in enumerate(triangles):
        a, b, c = (sub(v, origin) for v in t)
        volumes[root(i)] += dot(a, cross(b, c)) / 6.0
    result.update(degenerate_faces=degenerate, duplicate_faces=duplicate,
                  boundary_edges=boundary, edges_with_more_than_two_faces=nonmanifold,
                  inconsistent_winding_edges=winding, components=len(volumes),
                  signed_component_volumes_mm3=list(volumes.values()))
    for count, name in [(degenerate, 'degenerate_faces'), (duplicate, 'duplicate_faces'),
                        (boundary, 'open_boundary'), (nonmanifold, 'nonmanifold_edges'),
                        (winding, 'inconsistent_winding')]:
        if count:
            failures.append(name)
    if len(volumes) != expected_components:
        failures.append('unexpected_component_count')
    if any(v <= 1e-9 for v in volumes.values()):
        failures.append('nonpositive_component_volume')
    result['status'] = 'FAIL' if failures else 'PASS_LIMITED_SCREEN'
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stl', type=Path)
    parser.add_argument('--bed', nargs=3, type=float, default=[180, 180, 180])
    parser.add_argument('--margin', type=float, default=5.0)
    parser.add_argument('--expected-components', type=int, default=1)
    parser.add_argument('--expect-size', nargs=3, type=float)
    parser.add_argument('--dimension-tolerance', type=float, default=0.05)
    parser.add_argument('--weld-grid', type=float, default=1e-6)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        triangles, encoding, digest = read_stl(args.stl)
        result = audit(triangles, args.bed, args.margin, args.expected_components,
                       args.expect_size, args.dimension_tolerance, args.weld_grid)
        result.update(file=str(args.stl), encoding=encoding, sha256=digest)
        code = 0 if result['status'] == 'PASS_LIMITED_SCREEN' else 1
    except (ValueError, OSError, OverflowError, struct.error) as exc:
        result = {'status': 'ERROR', 'error': str(exc), 'limitations': LIMITS}
        code = 2
    rendered = json.dumps(result, indent=2, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + '\n')
    print(rendered)
    return code

if __name__ == '__main__':
    sys.exit(main())
