"""
Tests for DarkRadar signal in BrainHub.
"""
import struct
import pytest
import numpy as np
from synrix_runtime.monitoring.brain import BrainEvent, BrainHub, DarkRadar, MemoryHealth, LoopBreaker


def make_embedding(values):
    return struct.pack(f"{len(values)}f", *values)

def unit_vec(dim=4, index=0):
    v = [0.0] * dim
    v[index] = 1.0
    return make_embedding(v)

def zero_vec(dim=4):
    return make_embedding([0.0] * dim)


class MockBackend:
    def __init__(self, results):
        self._results = results
    def semantic_search(self, query_embedding, limit, threshold, name_prefix=""):
        return self._results


class TestDarkRadarNoneEmbedding:
    def test_none_returns_event(self):
        DarkRadar.reset("t1", "a1")
        e = DarkRadar.check("t1", "a1", "my_key", "val", embedding=None)
        assert e is not None and e.event_type == "dark"

    def test_none_increments_count(self):
        DarkRadar.reset("t1", "a2")
        DarkRadar.check("t1", "a2", "k1", "v1", embedding=None)
        DarkRadar.check("t1", "a2", "k2", "v2", embedding=None)
        assert DarkRadar.get_dark_count("t1", "a2") == 2


class TestDarkRadarZeroVector:
    def test_zero_bytes_returns_event(self):
        DarkRadar.reset("t2", "a1")
        e = DarkRadar.check("t2", "a1", "key", "val", embedding=zero_vec())
        assert e is not None and e.event_type == "dark"

    def test_zero_numpy_returns_event(self):
        DarkRadar.reset("t2", "a2")
        e = DarkRadar.check("t2", "a2", "key", "val", embedding=np.zeros(4, dtype=np.float32))
        assert e is not None and e.event_type == "dark"


class TestDarkRadarValidEmbedding:
    def test_valid_no_backend_returns_none(self):
        DarkRadar.reset("t3", "a1")
        e = DarkRadar.check("t3", "a1", "key", "val", embedding=unit_vec(), backend=None)
        assert e is None

    def test_valid_does_not_increment_count(self):
        DarkRadar.reset("t3", "a2")
        DarkRadar.check("t3", "a2", "key", "val", embedding=unit_vec(), backend=None)
        assert DarkRadar.get_dark_count("t3", "a2") == 0


class TestDarkRadarSearchVerification:
    def test_backend_no_results_flags_dark(self):
        DarkRadar.reset("t4", "a1")
        e = DarkRadar.check("t4", "a1", "target", "val",
                            embedding=unit_vec(), backend=MockBackend([]))
        assert e is not None and e.event_type == "dark"

    def test_backend_finds_key_returns_none(self):
        DarkRadar.reset("t4", "a2")
        e = DarkRadar.check("t4", "a2", "target", "val",
                            embedding=unit_vec(),
                            backend=MockBackend([{"key": "agents:a2:target", "score": 0.95}]))
        assert e is None

    def test_broken_backend_does_not_raise(self):
        class BrokenBackend:
            def semantic_search(self, **kwargs):
                raise RuntimeError("down")
        DarkRadar.reset("t4", "a3")
        e = DarkRadar.check("t4", "a3", "key", "val",
                            embedding=unit_vec(), backend=BrokenBackend())
        assert e is None


class TestDarkRadarReset:
    def test_reset_clears_count(self):
        DarkRadar.reset("t5", "a1")
        DarkRadar.check("t5", "a1", "k", "v", embedding=None)
        DarkRadar.reset("t5", "a1")
        assert DarkRadar.get_dark_count("t5", "a1") == 0


class TestBrainHubDarkIntegration:
    def test_process_write_none_embedding_includes_dark_event(self):
        events = BrainHub.process_write("t6", "a1", "lost", "gone", embedding=None)
        assert any(e.event_type == "dark" for e in events)

    def test_process_write_valid_embedding_no_dark_event(self):
        events = BrainHub.process_write("t6", "a2", "good", "findable", embedding=unit_vec())
        assert not any(e.event_type == "dark" for e in events)

    def test_get_brain_status_includes_dark_warnings(self):
        BrainHub.process_write("t7", "a1", "k", "v", embedding=None)
        status = BrainHub.get_brain_status("t7")
        assert "dark_warnings" in status
        assert status["dark_warnings"] >= 1
