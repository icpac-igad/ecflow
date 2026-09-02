# `deployment/` — the daily GIK workflow building blocks

**The full guide is the [repository root README](../README.md)** — what the workflow does,
how it's wired, how to operate it, and troubleshooting.

This folder holds the pieces:

```
docker/            engine stack — docker-compose(.crafd).yml, Makefile, images/ecflow (Dockerfile + entrypoint)
dashboard/         Prefect-style monitoring UI + host-executor bridge + systemd templates
pyflow/            config-driven Python-API suite generator (a new pipeline = a new YAML)
suites/include/    generic head.h / tail.h job includes
```

Quick start (on `crafd-gpu`):

```bash
cd ~/e4drr-ecflow && make up-crafd     # start engine + REST proxy (Tailscale + LAN)
```

Config comes from `.env` (copy `.env.example`; **secrets are never committed**).
Project-specific suites (the ECMWF IFS GIK pipeline, era files) live in the private
`cno-e4drr` repo, not here.
