#!/usr/bin/env python3

from contextlib import contextmanager
from threading import Lock


class RWLock(object):
    def __init__(self):
        self.lock = Lock()
        self.read_count = 0
        self.read_count_lock = Lock()

    def acquire_read(self):
        self.read_count_lock.acquire()
        self.read_count += 1
        if self.read_count == 1:
            self.lock.acquire()
        self.read_count_lock.release()

    def release_read(self):
        assert self.read_count > 0
        self.read_count_lock.acquire()
        self.read_count -= 1
        if self.read_count == 0:
            self.lock.release()
        self.read_count_lock.release()

    @contextmanager
    def read_lock(self):
        try:
            self.acquire_read()
            yield
        finally:
            self.release_read()

    def acquire_write(self):
        self.lock.acquire()

    def release_write(self):
        self.lock.release()

    @contextmanager
    def write_lock(self):
        try:
            self.acquire_write()
            yield
        finally:
            self.release_write()
