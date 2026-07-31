# pyflow workflow generator — ICPAC GIK daily pipelines

Modular Python-API (pyflow) definition of the daily GIK pipelines — the maintainable
alternative to hand-written `.def`/`.ecf` files (see cno-e4drr issue #2).

## Layout (modular — a new dataset is a new YAML, not new code)
```
configs/<name>.yaml   one file per pipeline: schedule, run cycle, executor, stages
gik_workflow/
  config.py           typed config loader
  scripts.py          reusable task-script generators (container->host bridge; stubs)
  pipeline.py         reusable daily-family builder (dataset-agnostic)
  suite.py            assemble a pyflow.Suite from a config
build.py              CLI: config -> .def
Dockerfile.pyflow     ecflow image + pyflow (authoring env)
```

## Build & test
```bash
docker build -t gik-pyflow -f Dockerfile.pyflow .
docker run --rm -v "$PWD:/w" -w /w gik-pyflow python build.py --config configs/gik.yaml   # print .def
```
`suite.deploy_suite()` writes the `.ecf` task scripts under `ECF_FILES`.

## Notes
- Empty `schedule:` → on-demand pipeline (backfills / local test), runs on begin.
  `schedule: "06:00"` → daily cron.
- Era selection (49r1 `enfo` / 50r1 `oper`) lives in the **host executor**, not the suite;
  the suite is era-agnostic. See cno-e4drr `ECFLOW_50R1_OPERATIONALIZATION.md`.
- **Verified locally**: builds, loads into ecflow, full stub chain auto-runs.
