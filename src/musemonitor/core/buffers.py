import numpy as np


class Ring:
    """Numpy ring buffer (n_ch × cap) — avoids deque → list conversions every frame."""
    def __init__(self, n_ch, cap):
        self.buf = np.zeros((n_ch, cap)); self.cap = cap; self.n = 0; self.i = 0

    def clear(self):
        self.n = 0; self.i = 0

    def extend(self, x):
        k = x.shape[1]
        if k >= self.cap:
            self.buf[:] = x[:, -self.cap:]; self.i = 0; self.n = self.cap; return
        end = self.i + k
        if end <= self.cap:
            self.buf[:, self.i:end] = x
        else:
            s = self.cap - self.i
            self.buf[:, self.i:] = x[:, :s]; self.buf[:, :end - self.cap] = x[:, s:]
        self.i = end % self.cap; self.n = min(self.cap, self.n + k)

    def get(self, n=None):
        """The newest n samples in time order (default: all) — copies only what is needed."""
        n = self.n if n is None else max(0, min(n, self.n))
        s = (self.i - n) % self.cap
        if s + n <= self.cap: return self.buf[:, s:s + n].copy()
        return np.concatenate([self.buf[:, s:], self.buf[:, :s + n - self.cap]], axis=1)
