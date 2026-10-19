"""A stand-in for pylsl in CI (no liblsl, no network): records every outlet and every push, in order.

``make()`` returns a fresh module object; put it in ``sys.modules["pylsl"]``. Only the calls the
lsl_outlet extension uses are implemented, with the same signatures as pylsl 1.16.2+.
"""
import types
import weakref

import numpy as np


class Node:
    """The XML tree of StreamInfo.desc()."""
    def __init__(self, name=""):
        self.name, self.children, self.value = name, [], None

    def append_child(self, name):
        n = Node(name); self.children.append(n); return n

    def append_child_value(self, name, value):
        n = Node(name); n.value = value; self.children.append(n); return self

    def child(self, name):
        return next((c for c in self.children if c.name == name), None)

    def child_value(self, name):
        c = self.child(name)
        return None if c is None else c.value

    def all(self, name):
        return [c for c in self.children if c.name == name]


def make():
    m = types.ModuleType("pylsl")
    m.log = []                      # (outlet name, "chunk" | "sample", values, timestamps) in push order
    m.outlets = []                  # weak references to every outlet ever created
    m.clock = [0.0]
    m.local_clock = lambda: m.clock[0]
    m.IRREGULAR_RATE = 0.0
    m.consumers = False             # what StreamOutlet.have_consumers() returns

    class StreamInfo:
        def __init__(self, name, type, channel_count, nominal_srate, channel_format, source_id):
            self._name, self._type, self._n = name, type, channel_count
            self._srate, self._fmt, self._source = nominal_srate, channel_format, source_id
            self._desc = Node("desc")

        def name(self): return self._name
        def type(self): return self._type
        def channel_count(self): return self._n
        def nominal_srate(self): return self._srate
        def channel_format(self): return self._fmt
        def source_id(self): return self._source
        def desc(self): return self._desc

    class StreamOutlet:
        def __init__(self, info, chunk_size=0, max_buffered=360):
            self.info = info
            m.outlets.append(weakref.ref(self))

        def push_chunk(self, x, timestamp=0.0, pushthrough=True):
            arr = np.asarray(x)
            assert isinstance(timestamp, list), "per-sample timestamps must be a list (pylsl's ctypes path)"
            assert all(type(t) is float for t in timestamp)
            assert arr.ndim == 2 and arr.shape == (len(timestamp), self.info.channel_count())
            m.log.append((self.info.name(), "chunk", arr.copy(), list(timestamp)))

        def have_consumers(self):
            return m.consumers

        def push_sample(self, x, timestamp=0.0, pushthrough=True):
            assert len(x) == self.info.channel_count()
            m.log.append((self.info.name(), "sample", list(x), [float(timestamp)]))

    m.StreamInfo, m.StreamOutlet = StreamInfo, StreamOutlet
    return m
