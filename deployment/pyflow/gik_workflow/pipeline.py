"""Reusable daily-pipeline family builder — dataset-agnostic.

Builds the stage tasks, chains them by trigger in order, and (if a schedule is set)
puts the daily cron on the family. A config with an empty schedule produces an
on-demand pipeline (backfills / testing) that runs as soon as it is begun."""
import pyflow as pf
from .scripts import bridge_script, stub_script


def daily_family(cfg, name: str = "day"):
    with pf.Family(name, RUN=cfg.run, RUN_DATE="") as fam:
        if cfg.schedule:
            pf.Cron(cfg.schedule)
        prev = None
        for st in cfg.stages:
            body = (bridge_script(cfg.executor, st.endpoint, st.timeout)
                    if st.endpoint else stub_script(st.title))
            task = pf.Task(st.name, script=body, KIND=st.kind, TITLE=st.title)
            if prev is not None:
                task.triggers = prev.complete
            prev = task
    return fam
