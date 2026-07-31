#!/usr/bin/env python3
"""Build a GIK ecFlow suite from config via the pyflow API.

  python build.py --config configs/gik.yaml            # print the .def
  python build.py --config configs/gik.yaml --def o.def # write the .def
"""
import argparse
from gik_workflow.config import load_config
from gik_workflow.suite import build_suite


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/gik.yaml")
    ap.add_argument("--def", dest="deffile")
    ap.add_argument("--files", default="/ecflow/suites")
    ap.add_argument("--home", default="/ecflow/home")
    a = ap.parse_args()
    cfg = load_config(a.config)
    suite = build_suite(cfg, files=a.files, home=a.home)
    text = str(suite.ecflow_definition())
    if a.deffile:
        open(a.deffile, "w").write(text)
        print("wrote", a.deffile)
    else:
        print(text)


if __name__ == "__main__":
    main()
