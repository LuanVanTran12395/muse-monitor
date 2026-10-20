"""The cube model and the view, both Qt-free.

Coordinates: x right, y up, z towards the viewer. Cubie positions use doubled units, ``2i − (n − 1)``, so a 2×2 has
coordinates ±1 and a 3×3 has −2, 0, 2. Each cubie carries its stickers as {outward normal: colour}; a turn rotates
the positions and the normals of one outer layer. A cube of size n has 6 × n² stickers (24 for 2×2, 54 for 3×3).

Layers: a move turns the layer at ``depth`` behind a face (0 = the face itself, n − 1 = the opposite face), clockwise
as seen from that face. Moves are stored canonically, in standard notation: an outer layer as (face, turns); the
opposite face's layer as that face's own move; the 3×3 middle slices as (L | D | F, turns, 1) = M | E | S.

The model knows only LOGICAL faces (U D L R F B of the cube as built). Turning the whole cube to look at a hidden face
changes only the ``View`` (a rotation, logical → screen); keys and gestures name SCREEN faces and the view maps them to
logical ones, so the move history, undo and the hint stay right whatever the view.
"""
import random

import numpy as np

FACES = "UDLRFB"
NORMAL = {"U": (0, 1, 0), "D": (0, -1, 0), "L": (-1, 0, 0), "R": (1, 0, 0), "F": (0, 0, 1), "B": (0, 0, -1)}
FACE_OF = {v: k for k, v in NORMAL.items()}
COLOURS = {"U": "white", "D": "yellow", "F": "red", "R": "blue", "B": "orange", "L": "green"}
AXIS = {"U": 1, "D": 1, "L": 0, "R": 0, "F": 2, "B": 2}
OPPOSITE = {"U": "D", "D": "U", "L": "R", "R": "L", "F": "B", "B": "F"}
SLICE = {"L": "M", "D": "E", "F": "S"}                 # the 3×3 middle slices, turning like L, D, F


def rot90(axis, quarter_turns):
    """Integer rotation matrix: ``quarter_turns`` × 90° counter-clockwise about the unit vector ``axis``."""
    k = np.asarray(axis, dtype=int)
    q = quarter_turns % 4
    c, s = (1, 0, -1, 0)[q], (0, 1, 0, -1)[q]
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return (c * np.eye(3, dtype=int) + s * kx + (1 - c) * np.outer(k, k)).astype(int)


def move_name(face, turns, depth=0):
    return (SLICE.get(face, face) if depth else face) + {1: "", 2: "2", 3: "′"}[turns % 4]


def parts(move):
    """(face, turns, depth) of a stored move (depth is left out for outer layers)."""
    return (move[0], move[1], move[2] if len(move) > 2 else 0)


def simplify(moves):
    """Merge consecutive turns of the same face; drop the ones that cancel."""
    out = []
    for m in moves:
        f, t, d = parts(m)
        if out and parts(out[-1])[0] == f and parts(out[-1])[2] == d:
            t = (parts(out.pop())[1] + t) % 4
        else:
            t %= 4
        if t: out.append((f, t) if d == 0 else (f, t, d))
    return out


def inverse(moves):
    return [(m[0], (-m[1]) % 4) + tuple(m[2:]) for m in reversed(moves)]


class Cube:
    def __init__(self, n=2):
        if n not in (2, 3): raise ValueError("n must be 2 or 3")
        self.n = n
        self.edge = n - 1                                   # outer coordinate (doubled units)
        coords = range(-self.edge, self.edge + 1, 2)
        self.cubies = []
        for x in coords:
            for y in coords:
                for z in coords:
                    p = np.array([x, y, z])
                    st = {}
                    for f, nrm in NORMAL.items():
                        if int(np.dot(p, nrm)) == self.edge: st[nrm] = COLOURS[f]
                    if st: self.cubies.append(dict(pos=p, stickers=st, home=p.copy()))
        self.scrambled = []                                 # the scramble (logical moves)
        self.history = []                                   # the player's moves since the scramble (logical)

    def sticker_count(self):
        return sum(len(c["stickers"]) for c in self.cubies)

    def layer(self, face, depth=0):
        nrm = np.array(NORMAL[face])
        return [c for c in self.cubies if int(np.dot(c["pos"], nrm)) == self.edge - 2 * depth]

    def canonical(self, face, turns, depth=0):
        """The stored form of a layer move (see the module docstring)."""
        if not 0 <= depth < self.n: raise ValueError(f"depth {depth} outside 0..{self.n - 1}")
        turns %= 4
        if depth == self.n - 1 and depth > 0:                  # the opposite face, turned from its own side
            return (OPPOSITE[face], (-turns) % 4)
        if depth == 0: return (face, turns)
        if face not in SLICE:                                  # middle slice: named after L / D / F
            face, depth, turns = OPPOSITE[face], self.n - 1 - depth, (-turns) % 4
        return (face, turns, depth)

    def turn(self, face, turns=1, record=True, depth=0):
        """The layer ``depth`` behind a logical face, clockwise as seen looking at that face (turns −1 / 3 =
        counter-clockwise). Returns the canonical move."""
        move = self.canonical(face, turns, depth)
        f, t, d = parts(move)
        m = rot90(NORMAL[f], -t)
        for c in self.layer(f, d):
            c["pos"] = m @ c["pos"]
            c["stickers"] = {tuple(int(v) for v in m @ np.array(k)): col for k, col in c["stickers"].items()}
        if record: self.history.append(move)
        return move

    def solved(self):
        for nrm in NORMAL.values():
            cols = {c["stickers"][nrm] for c in self.cubies if nrm in c["stickers"]}
            if len(cols) != 1: return False
        return True

    def scramble(self, length, seed=None):
        rng = random.Random(seed)
        moves, last_axis = [], None
        while len(moves) < length:
            f = rng.choice(FACES)
            if AXIS[f] == last_axis: continue               # no two turns on one axis in a row (they could cancel)
            moves.append((f, rng.choice((1, 2, 3)))); last_axis = AXIS[f]
        for f, t in moves: self.turn(f, t, record=False)
        self.scrambled, self.history = moves, []          # scrambles use the outer layers only
        return moves

    def undo(self):
        if not self.history: return None
        move = self.history.pop()
        f, t, d = parts(move)
        self.turn(f, -t, record=False, depth=d)
        return move

    def way_back(self):
        """The moves back to the solved state: the inverse of scramble + history, simplified. Always solves, NOT an
        optimal solution (it can be long). Used as the hint."""
        return simplify(inverse(self.scrambled + self.history))


class View:
    """Which way the cube is held: ``R`` maps logical directions to screen directions (axis-aligned)."""

    TURNS = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}

    def __init__(self):
        self.R = np.eye(3, dtype=int)

    def turn(self, axis, quarter_turns):
        """Turn the whole cube about a screen axis (x / y / z, counter-clockwise looking from + along it)."""
        self.R = rot90(self.TURNS[axis], quarter_turns) @ self.R

    def logical(self, screen_face):
        """The logical face now showing at the screen face U / D / L / R / F / B."""
        return FACE_OF[tuple(int(v) for v in self.R.T @ np.array(NORMAL[screen_face]))]

    def screen(self, logical_face):
        return FACE_OF[tuple(int(v) for v in self.R @ np.array(NORMAL[logical_face]))]
