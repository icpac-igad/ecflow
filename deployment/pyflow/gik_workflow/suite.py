"""Assemble an ecFlow suite from a workflow config using pyflow."""
import pyflow as pf
from .pipeline import daily_family


def build_suite(cfg, files="/ecflow/suites", home="/ecflow/home"):
    with pf.Suite(cfg.suite, host=pf.LocalHost(), files=files, home=home) as s:
        daily_family(cfg)
    return s
