"""Avrana home: adapter layer (proposed, not deployed; synthetic data only).

Import-only library code. No server, no template, no network at import time.
"""
import logging as _logging

# Library convention: no output unless the application configures logging.
_logging.getLogger("avrana_home").addHandler(_logging.NullHandler())
