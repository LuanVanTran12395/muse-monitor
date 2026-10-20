"""Stimulus schedule — pure Python (no Qt, no clock): a seed and a configuration give the same plan every time.

Structure (debate/claude-p300-extension-proposal.md §4.1):
    block → trials → [cue on target][blank] R repetitions × (every flashing cell once, random order) [tail]
                     [count question, optional]
    rest between blocks.
R can vary per trial (``repetitions ± repetitions_jitter``, drawn from the seed) so the count the participant reports
at the optional question is not always the same number (attention check).
Times are seconds relative to the session start ``t0``; the runner adds the monotonic ``t0`` when it starts.
"""
import random
from dataclasses import asdict, dataclass, field

GRID = 3                                                    # 3 × 3 cells, index = row * 3 + col
COMMANDS = {1: "Forward", 3: "Turn left", 4: "Stop", 5: "Turn right", 7: "Backward"}   # the 5 command cells
FLASHING = tuple(sorted(COMMANDS))                          # Q1: only the command cells flash (target p = 1/5)


@dataclass
class Config:
    soa_s: float = 0.400            # stimulus onset asynchrony (paper: 400 ms)
    flash_s: float = 0.100          # how long a cell stays lit (paper: 100 ms)
    repetitions: int = 10           # R: every flashing cell flashes R times per trial
    trials_per_block: int = 5
    blocks: int = 2
    rest_s: float = 30.0            # between blocks
    cue_s: float = 1.0              # target cell outlined before the flashes
    blank_s: float = 0.5            # after the cue, before the first flash
    tail_s: float = 1.0             # after the last flash (room for the last epoch)
    iti_s: float = 1.0              # between trials
    seed: int = 1
    mode: str = "eeg_only"          # "eeg_only" | "response_assisted" (Space recorded, results reported apart)
    repetitions_jitter: int = 0     # R of each trial drawn uniformly in repetitions ± this (0 = every trial R)
    ask_s: float = 0.0              # after each trial: "how many times did the target flash?" window (0 = no question)

    def errors(self):
        """Human-readable problems; empty = valid."""
        e = []
        if not 0.3 <= self.soa_s <= 2.0: e.append("Stimulus interval must be 300–2000 ms.")
        if not 0.05 <= self.flash_s <= self.soa_s - 0.05:
            e.append("Flash duration must be at least 50 ms and 50 ms shorter than the interval.")
        if not 1 <= self.repetitions <= 30: e.append("Repetitions must be 1–30.")
        j = self.repetitions_jitter
        if not isinstance(j, int) or j < 0 or self.repetitions - j < 1 or self.repetitions + j > 30:
            e.append("Repetition variation must keep every trial within 1–30 repetitions.")
        if not (self.ask_s == 0 or 2 <= self.ask_s <= 20): e.append("Count question must be 0 (off) or 2–20 s.")
        if not 1 <= self.trials_per_block <= 100: e.append("Trials per block must be 1–100.")
        if not 1 <= self.blocks <= 20: e.append("Blocks must be 1–20.")
        if not 0 <= self.rest_s <= 600: e.append("Rest must be 0–600 s.")
        if not 0.2 <= self.cue_s <= 5: e.append("Cue must be 0.2–5 s.")
        if self.blank_s < 0 or self.tail_s < 0 or self.iti_s < 0: e.append("Blank, tail and pause must be ≥ 0.")
        if not isinstance(self.seed, int) or self.seed < 0: e.append("Seed must be a non-negative integer.")
        if self.mode not in ("eeg_only", "response_assisted"): e.append("Unknown mode.")
        return e

    def to_dict(self):
        return asdict(self)


@dataclass
class Stim:
    seq: int            # 0, 1, 2 … over the session
    block: int
    trial: int          # over the session
    rep: int            # 0 … R−1 within the trial
    cell: int
    is_target: bool
    on_s: float         # planned onset, relative to t0
    off_s: float


@dataclass
class Trial:
    trial: int
    block: int
    target: int
    cue_on_s: float
    cue_off_s: float
    first_flash_s: float
    end_s: float
    repetitions: int = 0            # R of this trial (= the right answer to the count question)
    ask_on_s: float = None          # count question window (None = no question)
    ask_off_s: float = None


@dataclass
class Plan:
    config: Config
    trials: list = field(default_factory=list)
    stims: list = field(default_factory=list)
    rests: list = field(default_factory=list)       # (start_s, end_s)
    duration_s: float = 0.0


def _targets(n, rng):
    """Balanced targets: every command cell once per cycle, each cycle shuffled."""
    out = []
    while len(out) < n:
        cycle = list(FLASHING); rng.shuffle(cycle)
        if out and cycle[0] == out[-1] and len(cycle) > 1: cycle[0], cycle[1] = cycle[1], cycle[0]
        out += cycle
    return out[:n]


def _repetition(rng, previous_last):
    """One repetition: every flashing cell once, never starting with the cell that ended the previous one."""
    order = list(FLASHING); rng.shuffle(order)
    if previous_last is not None and order[0] == previous_last:
        order[0], order[1] = order[1], order[0]
    return order


def build(config):
    """The whole plan for a valid configuration (ValueError otherwise)."""
    errs = config.errors()
    if errs: raise ValueError(" ".join(errs))
    rng = random.Random(config.seed)
    plan = Plan(config)
    targets = _targets(config.trials_per_block * config.blocks, rng)
    t, seq, n_trial = 0.0, 0, 0
    for block in range(config.blocks):
        for _ in range(config.trials_per_block):
            target = targets[n_trial]
            cue_on, cue_off = t, t + config.cue_s
            first = cue_off + config.blank_s
            last_cell, k = None, 0
            reps = config.repetitions
            if config.repetitions_jitter:           # drawn only when used: plans of older configs stay identical
                reps = rng.randint(reps - config.repetitions_jitter, reps + config.repetitions_jitter)
            for rep in range(reps):
                order = _repetition(rng, last_cell)
                for cell in order:
                    on = first + k * config.soa_s
                    plan.stims.append(Stim(seq, block, n_trial, rep, cell, cell == target, on, on + config.flash_s))
                    seq += 1; k += 1
                last_cell = order[-1]
            end = first + (k - 1) * config.soa_s + config.flash_s + config.tail_s
            ask_on = ask_off = None
            if config.ask_s > 0:                    # after the tail: no flash epoch contains the key presses
                ask_on, ask_off = end, end + config.ask_s; end = ask_off
            plan.trials.append(Trial(n_trial, block, target, cue_on, cue_off, first, end, reps, ask_on, ask_off))
            n_trial += 1
            t = end + config.iti_s
        if block < config.blocks - 1 and config.rest_s > 0:
            plan.rests.append((t, t + config.rest_s)); t += config.rest_s
    plan.duration_s = t
    return plan


# ---- actions the runner executes, in time order -------------------------------------------------------
@dataclass(order=True)
class Action:
    t_s: float                      # relative to t0
    order: int                      # tie-break: offs before ons at the same instant
    kind: str = field(compare=False)  # cue_on | cue_off | flash_on | flash_off | ask_on | ask_off | trial_start |
                                      # trial_end | rest_on | rest_off | done
    ref: object = field(compare=False, default=None)   # Stim, Trial or (start, end)


def actions(plan):
    out = []
    for tr in plan.trials:
        out += [Action(tr.cue_on_s, 2, "trial_start", tr), Action(tr.cue_on_s, 3, "cue_on", tr),
                Action(tr.cue_off_s, 1, "cue_off", tr), Action(tr.end_s, 0, "trial_end", tr)]
        if tr.ask_on_s is not None:                 # the answer is closed before the trial row is written
            out += [Action(tr.ask_on_s, 2, "ask_on", tr), Action(tr.ask_off_s, -1, "ask_off", tr)]
    for st in plan.stims:
        out += [Action(st.on_s, 3, "flash_on", st), Action(st.off_s, 1, "flash_off", st)]
    for r in plan.rests:
        out += [Action(r[0], 2, "rest_on", r), Action(r[1], 1, "rest_off", r)]
    out.append(Action(plan.duration_s, 9, "done"))
    return sorted(out)


class Runner:
    """Steps through the actions against a monotonic clock supplied by the caller (testable without Qt)."""
    def __init__(self, plan, t0):
        self.t0 = t0
        self.queue = actions(plan)
        self.i = 0

    def next_due(self):
        """Absolute monotonic time of the next action, or None when finished."""
        return None if self.i >= len(self.queue) else self.t0 + self.queue[self.i].t_s

    def pop_due(self, now, slack_s=0.0005):
        """Actions due at ``now`` (with a small slack), in order, each with its absolute planned time."""
        out = []
        while self.i < len(self.queue) and self.t0 + self.queue[self.i].t_s <= now + slack_s:
            a = self.queue[self.i]; out.append((self.t0 + a.t_s, a)); self.i += 1
        return out

    @property
    def finished(self):
        return self.i >= len(self.queue)
