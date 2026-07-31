"""Modular pyflow builder for the ICPAC GIK daily pipelines.

config.py    one dataclass per config file (add a dataset -> add a YAML)
scripts.py   reusable task-script generators (the container->host bridge pattern)
pipeline.py  reusable daily-pipeline family builder (dataset-agnostic)
suite.py     assemble a pyflow.Suite from a config
"""
