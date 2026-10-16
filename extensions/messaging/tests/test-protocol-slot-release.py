#!/usr/bin/env python3
"""Disconnected clients must not permanently exhaust broker concurrency."""
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('protocol', Path(__file__).parents[1] / 'unified/protocol.py')
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)

class BrokenClose(io.BytesIO):
    def close(self):
        if self.closed: return
        super().close()
        raise BrokenPipeError('client disconnected during stream close')

class Connection:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): pass
    def makefile(self, mode): return BrokenClose(b'{"op":"probe"}\n')
    def close(self): pass

class Listener:
    def __init__(self): self.count = 0
    def accept(self):
        self.count += 1
        if self.count > 17: raise KeyboardInterrupt
        return Connection(), None

class ImmediateThread:
    def __init__(self, target, args, daemon): self.target, self.args = target, args
    def start(self):
        try: self.target(*self.args)
        except OSError: pass

class SlotReleaseTest(unittest.TestCase):
    def test_seventeen_disconnected_clients_do_not_exhaust_sixteen_slots(self):
        handled = []
        with patch('threading.Thread', ImmediateThread):
            with self.assertRaises(KeyboardInterrupt):
                protocol.serve_socket(Listener(), lambda request: handled.append(request) or {}, concurrent=True)
        self.assertEqual(len(handled), 17)

if __name__ == '__main__': unittest.main()
