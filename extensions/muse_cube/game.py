"""One game: a scrambled cube, the view, the clock and the result — Qt-free.

Every command names a SCREEN face or axis; the view maps it to the logical cube (see cube.py), so the history, undo
and the way back stay right after the player turns the whole cube. A game in which the way back (hint) was shown is
marked ``hinted``: it is kept, but not ranked with games solved alone.
"""
from .cube import Cube, View, move_name, parts

DEPTHS = {2: (3, 5, 8, 11), 3: (3, 5, 8, 12)}          # scramble lengths per level


class Game:
    def __init__(self, n=2, depth=3, seed=None, clock=None):
        import time
        self.clock = clock or time.monotonic
        self.new(n, depth, seed)

    def new(self, n=None, depth=None, seed=None):
        """depth 0: an unscrambled practice cube that never finishes (the tutorial's first steps)."""
        self.n = n or getattr(self, "n", 2)
        self.depth = depth if depth is not None else getattr(self, "depth", 3)
        self.cube, self.view = Cube(self.n), View()
        self.practice = self.depth == 0
        self.scramble = self.cube.scramble(self.depth, seed)
        if self.cube.solved() and not self.practice:     # rare (short scrambles can cancel): try another seed
            self.scramble = self.cube.scramble(self.depth, None if seed is None else seed + 1)
        self.started = None                              # the clock starts on the first turn
        self.finished = None
        self.moves = self.undos = self.view_turns = 0
        self.hinted = False
        self.hint = None                                 # way-back step: (screen face, turns, steps left, depth)

    # ---- commands (screen terms) -------------------------------------------------------------------------------
    def turn(self, screen_face, turns=1, depth=0):
        """Turn the layer ``depth`` behind the face now showing at ``screen_face`` (0 = that face). Returns the
        logical move (canonical), or None when finished."""
        if self.finished is not None: return None
        if self.started is None: self.started = self.clock()
        move = self.cube.turn(self.view.logical(screen_face), turns, depth=depth)
        self.moves += 1
        self.hint = None
        if self.cube.solved() and not self.practice: self.finished = self.clock()
        return move

    def undo(self):
        if self.finished is not None or not self.cube.history: return None
        m = self.cube.undo()
        self.undos += 1
        self.hint = None
        return m

    def turn_view(self, axis, quarter_turns):
        """Turn the whole cube to look at another face: the view only, never the history."""
        self.view.turn(axis, quarter_turns)
        self.view_turns += 1
        if self.hint: self.show_hint()                   # the same step, named for the new view

    def show_hint(self):
        """The next step of the way back to the start (NOT an optimal solution), in screen terms."""
        if self.finished is not None: return None
        back = self.cube.way_back()
        if not back: return None
        self.hinted = True
        face, turns, depth = parts(back[0])
        self.hint = (self.view.screen(face), turns, len(back), depth)
        return self.hint

    # ---- state ---------------------------------------------------------------------------------------------------
    @property
    def solved(self):
        return self.finished is not None

    def elapsed(self):
        if self.started is None: return 0.0
        return (self.finished if self.finished is not None else self.clock()) - self.started

    def result(self):
        return dict(n=self.n, depth=self.depth, seconds=round(self.elapsed(), 1), moves=self.moves,
                    undos=self.undos, view_turns=self.view_turns, hinted=self.hinted,
                    scramble=" ".join(move_name(*parts(m)) for m in self.scramble))
