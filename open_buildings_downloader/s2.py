"""Minimal S2 geometry: which S2 cells (at one level) cover a lat/lng area.

Google Open Buildings v3 ships one file per S2 cell, named by the cell token.
Only the parts of S2 needed to name those cells and draw their outlines
are here.
"""

import math

MAX_LEVEL = 30
MAX_SIZE = 1 << MAX_LEVEL

# Hilbert curve tables, as in the reference S2 implementation.
SWAP_MASK = 1
INVERT_MASK = 2
IJ_TO_POS = [[0, 1, 3, 2], [0, 3, 1, 2], [2, 3, 1, 0], [2, 1, 3, 0]]
POS_TO_ORIENTATION = [SWAP_MASK, 0, 0, INVERT_MASK | SWAP_MASK]


def _xyz_to_face_uv(x, y, z):
    ax, ay, az = abs(x), abs(y), abs(z)
    if ax >= ay and ax >= az:
        face = 0 if x > 0 else 3
    elif ay >= az:
        face = 1 if y > 0 else 4
    else:
        face = 2 if z > 0 else 5
    if face == 0:
        return face, y / x, z / x
    if face == 1:
        return face, -x / y, z / y
    if face == 2:
        return face, -x / z, -y / z
    if face == 3:
        return face, z / x, y / x
    if face == 4:
        return face, z / y, -x / y
    return face, -y / z, -x / z


def _face_uv_to_xyz(face, u, v):
    return [
        (1, u, v),
        (-u, 1, v),
        (-u, -v, 1),
        (-1, -v, -u),
        (v, -1, -u),
        (v, u, -1),
    ][face]


def _uv_to_st(u):
    if u >= 0:
        return 0.5 * math.sqrt(1 + 3 * u)
    return 1 - 0.5 * math.sqrt(1 - 3 * u)


def _st_to_uv(s):
    if s >= 0.5:
        return (4 * s * s - 1) / 3
    return (1 - 4 * (1 - s) * (1 - s)) / 3


def _st_to_ij(s):
    return max(0, min(MAX_SIZE - 1, int(math.floor(s * MAX_SIZE))))


def face_ij(lat, lng):
    """Leaf-cell (face, i, j) containing a lat/lng in degrees."""
    phi, theta = math.radians(lat), math.radians(lng)
    x = math.cos(phi) * math.cos(theta)
    y = math.cos(phi) * math.sin(theta)
    z = math.sin(phi)
    face, u, v = _xyz_to_face_uv(x, y, z)
    return face, _st_to_ij(_uv_to_st(u)), _st_to_ij(_uv_to_st(v))


def cell_id(face, i, j, level):
    """S2 cell id of the level-`level` cell holding leaf (face, i, j)."""
    orientation = face & SWAP_MASK
    pos = 0
    for k in range(MAX_LEVEL - 1, MAX_LEVEL - 1 - level, -1):
        ij = (((i >> k) & 1) << 1) | ((j >> k) & 1)
        p = IJ_TO_POS[orientation][ij]
        pos = (pos << 2) | p
        orientation ^= POS_TO_ORIENTATION[p]
    shift = 2 * (MAX_LEVEL - level)
    return (face << 61) | (pos << (shift + 1)) | (1 << shift)


def token(cid):
    return ('%016x' % cid).rstrip('0') or 'X'


class Cell:
    """A cell at some level: its face and (i, j) corner in leaf units."""

    def __init__(self, face, i, j, level):
        size = 1 << (MAX_LEVEL - level)
        self.face = face
        self.i0 = (i // size) * size
        self.j0 = (j // size) * size
        self.size = size
        self.level = level
        self.token = token(cell_id(face, i, j, level))

    def boundary(self, points_per_edge=16):
        """Closed ring of (lng, lat). Edges are straight in (u, v),
        which makes them great-circle arcs, so sampling along u/v is exact."""
        corners = [(0, 0), (1, 0), (1, 1), (0, 1)]
        ring = []
        for (a0, b0), (a1, b1) in zip(corners, corners[1:] + corners[:1]):
            for n in range(points_per_edge):
                t = n / points_per_edge
                si = (self.i0 + (a0 + (a1 - a0) * t) * self.size) / MAX_SIZE
                sj = (self.j0 + (b0 + (b1 - b0) * t) * self.size) / MAX_SIZE
                x, y, z = _face_uv_to_xyz(
                    self.face, _st_to_uv(si), _st_to_uv(sj)
                )
                lat = math.degrees(math.atan2(z, math.hypot(x, y)))
                lng = math.degrees(math.atan2(y, x))
                ring.append((lng, lat))
        ring.append(ring[0])
        return ring


# Smallest level-6 cell is ~0.84 degrees wide on the sphere; sampling a grid
# finer than that (diagonal included) cannot step over a cell.
GRID_STEP_DEG = 0.4


def cells_in_bbox(xmin, ymin, xmax, ymax, level):
    """Every level-`level` cell touching the lat/lng box (may include a few
    extra cells near the edges; callers filter by exact outline)."""
    found = {}
    nx = max(1, int(math.ceil((xmax - xmin) / GRID_STEP_DEG)))
    ny = max(1, int(math.ceil((ymax - ymin) / GRID_STEP_DEG)))
    for a in range(nx + 1):
        lng = xmin + (xmax - xmin) * a / nx
        for b in range(ny + 1):
            lat = ymin + (ymax - ymin) * b / ny
            face, i, j = face_ij(lat, lng)
            cell = Cell(face, i, j, level)
            found.setdefault(cell.token, cell)
    return list(found.values())
