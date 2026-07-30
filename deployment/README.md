# ecFlow deployment (ICPAC / E4DRR)

Container deployment of the ecFlow engine + REST proxy, per `docs/ecflow_ecosystem_strategy.md`
and `docs/README.md` (Scenario B: an always-on server + REST monitoring tier).

## `docker/`
Docker-compose stack running `ecflow_server` (+ `ecflow_http` REST proxy) from the
conda-forge image; bind-mounts suite definitions and state.

    make up-crafd     # start on a host, reachable over Tailscale + LAN
    make smoke        # load the hello smoke-test suite

Config comes from `.env` (copy `.env.example`; **secrets are never committed**). The
`docker-compose.crafd.yml` overlay publishes on host interfaces via env vars only.

## `suites/include/`
Generic ecFlow job includes (`head.h`, `tail.h`) — the init/complete/abort preamble
every `.ecf` task uses.

Project-specific suites (e.g. the ECMWF IFS GIK daily pipeline) live in the operating
project's own private repo, not here.
