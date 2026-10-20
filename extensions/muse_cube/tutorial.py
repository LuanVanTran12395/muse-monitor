"""The tutorial before the real game — Qt-free. Each step waits for the player to do it (head, or keys / mouse).

    select   pick the right face           point right · click it
    layer    the next layer behind it      nod · click it again / Tab / Next layer
    turn     turn the selected layer       tilt · ↺ ↻ / U D L R F B
    undo     undo that turn                shake · Backspace
    view     turn the whole cube           full turn and back · arrow keys
    solve1   a cube scrambled by 1 move    (H: the way back)
    solve2   scrambled by 2 moves
    done     ready → the real game         nod · Enter / the button

Steps 1–5 run on an unscrambled practice cube that never "finishes" (any move can be made and undone).
"""
STEPS = ("select", "layer", "turn", "undo", "view", "solve1", "solve2", "done")
SOLVE_DEPTH = {"solve1": 1, "solve2": 2}
CHEER_S = 1.2


class Tutorial:
    def __init__(self, clock):
        self.clock = clock
        self.i = 0
        self.cheer_until = None                    # "✓ well done" after a step

    @property
    def step(self):
        return STEPS[self.i]

    @property
    def finished(self):
        return self.step == "done"

    def on_command(self, name, board):
        """Called after every command the board ran. Returns True when the step was completed (the board then sets
        up the next one)."""
        s = self.step
        ok = ((s == "select" and name == "select" and board.selected == "R") or
              (s == "layer" and name == "layer" and board.depth > 0) or
              (s == "turn" and name == "turn") or
              (s == "undo" and name == "undo") or
              (s == "view" and name == "view") or
              (s in SOLVE_DEPTH and board.game.solved))
        if ok:
            self.i += 1
            self.cheer_until = self.clock() + CHEER_S
        return ok

    def cheering(self):
        return self.cheer_until is not None and self.clock() < self.cheer_until
