"""The 2D views next to the 3D cube, Qt-free geometry (screen terms: the faces as the cube is now held).

**Three ring clusters.** Every axis is a cluster of n concentric rings, one per layer: top cluster U · E · D (y),
right cluster R · M · L (x), left cluster F · S · B (z); the outer ring is the positive face (U, R, F), the inner one
the negative face (D, L, B). A sticker lies where two rings of the OTHER two axes cross — the two layers it moves with
besides its own face — on the side of its own axis' cluster for the positive face (U, R, F), across for the negative
one (D, L, B).
Turning a layer moves the stickers on its ring along that ring.

**Cross.** The classic unfolded net: U above F, then L F R B, D below F.
"""
import math

import numpy as np

CLUSTER = {1: ("U", "E", "D"), 0: ("R", "M", "L"), 2: ("F", "S", "B")}      # outer → inner (3×3)
CLUSTER_2 = {1: ("U", "D"), 0: ("R", "L"), 2: ("F", "B")}
# cluster centres around the common centroid, on the side of their labels (screen y points down)
DIRECTION = {1: (0.0, -1.0), 0: (math.cos(math.radians(30)), 0.5), 2: (-math.cos(math.radians(30)), 0.5)}
LABEL_DEG = {1: (-60.0, -120.0), 0: (60.0, 0.0), 2: (180.0, 120.0)}         # (X, X′) button angles on each ring
TURN_AS = {"E": ("D", 1), "M": ("L", 1), "S": ("F", 1)}                      # middle slices turn like D, L, F
SIGN = {"U": 1, "R": 1, "F": 1, "D": -1, "L": -1, "B": -1}
AXIS_OF = {"U": 1, "D": 1, "E": 1, "R": 0, "L": 0, "M": 0, "F": 2, "B": 2, "S": 2}


class Rings:
    """Layout of the three clusters, ``size`` wide, its bounding box centred at (cx, cy). Proportions from the
    reference picture: centres 0.2 × size from the common centroid, rings 0.21 … 0.33 × size."""

    def __init__(self, n, cx, cy, size):
        self.n, self.edge = n, n - 1
        s = size
        self.r_in, self.r_out = 0.2145 * s, 0.3275 * s
        self.step = (self.r_out - self.r_in) / max(1, n - 1)
        self.delta = 0.1986 * s
        oy = cy + 0.05 * s                                       # the centroid sits a little below the box centre
        self.centres = {a: np.array((cx + self.delta * dx, oy + self.delta * dy)) for a, (dx, dy) in DIRECTION.items()}

    def radius(self, axis, coord):
        """Ring of the layer at ``coord`` (doubled units, −edge … edge) along ``axis``."""
        return self.r_in + self.step * (coord + self.edge) / 2

    def rings(self):
        """[(axis, coord, name, (turn face, depth))] — name as printed (U, E, D…)."""
        names = CLUSTER if self.n == 3 else CLUSTER_2
        out = []
        for axis, labels in names.items():
            for i, name in enumerate(labels):
                coord = self.edge - 2 * i
                face, depth = TURN_AS.get(name, (name, 0))
                out.append((axis, coord, name, (face, depth)))
        return out

    def ring_of(self, face, depth):
        """(axis, coord) of the layer ``depth`` behind a screen face."""
        return AXIS_OF[face], SIGN[face] * (self.edge - 2 * depth)

    def label_points(self, axis, coord):
        """The (X, X′) buttons of a ring; inner rings' buttons step towards each other (9° per ring) so the buttons
        of neighbouring rings do not overlap."""
        c, r = self.centres[axis], self.radius(axis, coord)
        a, b = LABEL_DEG[axis]
        step = 9.0 * (self.edge - coord) / 2                    # 0 for the outer ring
        towards = 1 if (b - a) % 360 < 180 else -1
        degs = (a + towards * step, b - towards * step)
        return [c + r * np.array((math.cos(math.radians(d)), math.sin(math.radians(d)))) for d in degs]

    def point(self, pos, nrm):
        """Where the sticker at cubie ``pos`` with outward normal ``nrm`` (screen axes, ints) is drawn."""
        a = int(np.argmax(np.abs(nrm)))
        b, c = [k for k in (0, 1, 2) if k != a]
        p1, p2 = _intersections(self.centres[b], self.radius(b, int(pos[b])), self.centres[c], self.radius(c, int(pos[c])))
        far = p1 if np.linalg.norm(p1 - self.centres[a]) >= np.linalg.norm(p2 - self.centres[a]) else p2
        near = p2 if far is p1 else p1
        return near if nrm[a] > 0 else far          # U / R / F next to their own cluster; D / L / B across


def _intersections(c1, r1, c2, r2):
    d = float(np.linalg.norm(c2 - c1))
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    m = c1 + a * (c2 - c1) / d
    perp = np.array((-(c2 - c1)[1], (c2 - c1)[0])) / d
    return m + h * perp, m - h * perp


# ---- cross (unfolded net) ----------------------------------------------------------------------------------------
NET_AT = {"U": (1, 0), "L": (0, 1), "F": (1, 1), "R": (2, 1), "B": (3, 1), "D": (1, 2)}     # (column, row) of faces
NET_AXES = {"F": ((1, 0, 0), (0, 1, 0)), "R": ((0, 0, -1), (0, 1, 0)), "B": ((-1, 0, 0), (0, 1, 0)),
            "L": ((0, 0, 1), (0, 1, 0)), "U": ((1, 0, 0), (0, 0, -1)), "D": ((1, 0, 0), (0, 0, 1))}
FACE_NORMAL = {"U": (0, 1, 0), "D": (0, -1, 0), "L": (-1, 0, 0), "R": (1, 0, 0), "F": (0, 0, 1), "B": (0, 0, -1)}


def net_cell(n, pos, nrm):
    """(face, column, row) in the net for a sticker (screen axes): column / row within its face, 0 … n − 1."""
    face = next(f for f, v in FACE_NORMAL.items() if tuple(int(x) for x in nrm) == v)
    right, up = NET_AXES[face]
    edge = n - 1
    col = (int(np.dot(pos, right)) + edge) // 2
    row = (edge - int(np.dot(pos, up))) // 2
    return face, col, row
