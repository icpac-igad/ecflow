# Why a Workflow Management System — for Impact-Based Forecasting and Continuous Risk Monitoring

**A plain-language introduction for forecasters, analysts, and their managers**

- Audience: people who run daily/near-real-time forecast and risk products (and the teams and managers who depend on them), not only software engineers.
- Companion technical docs: `ecflow_vs_prefect_and_deployment.md` (tool choice, deployment, sizing).

---

## 1. The problem this solves

Most operational forecasting and risk work starts the same way: **one skilled person writes a script or a notebook** that downloads some data, runs a model or an analysis, makes a map or a table, and emails it out. It works. Then:

- That person goes on leave, and nobody else can run it.
- The download step fails silently at 02:00 and the 08:00 briefing has no product.
- A second person builds their own script for a related product, with its own `cron` entry on their own laptop or a random VM.
- A third product depends on the first two — but nobody knows if they finished, or in what order they must run.
- A manager asks "did today's flood risk product run, and is it correct?" and the only way to answer is to phone the person who wrote it.

This is the natural end-state of **individual scripts glued together with `cron` and good intentions**. It is fragile, invisible, and unshareable. The knowledge lives in one head; the status lives nowhere.

A **Workflow Management System (WMS)** replaces that with a single, shared, monitored place where all these steps are *defined, scheduled, connected, watched, and recovered* — so the whole team and beyond can see and trust what is happening.

---

## 2. What impact-based forecasting and continuous risk monitoring actually demand

Impact-Based Forecasting (IBF) and continuous risk monitoring are not single scripts — they are **chains** that must run reliably, on time, every day (or every hour), forever. The WMO impact-based approach turns a weather forecast into a *decision-ready risk product* by combining several data streams along a chain:

```
   Hazard forecast   ×   Exposure   ×   Vulnerability   →   Impact / Risk   →   Alert & product
  (rain, wind, heat)   (people,        (coping capacity,     (who & what is      (maps, bulletins,
                        assets, crops)   infrastructure)       likely affected)     dashboards)
```

Each box is one or more processing steps, often owned by *different* people or teams (a meteorologist owns the hazard forecast; a GIS/exposure analyst owns population and asset layers; a risk analyst owns vulnerability and thresholds; a communications officer owns the published product). The operational reality imposes hard requirements:

1. **Timeliness.** Forecasts and alerts are worthless late. The chain must start when new data lands and finish before the briefing/decision window.
2. **Dependencies.** Impact cannot be computed before the hazard forecast is ready and the exposure layers are current. Steps must run *in the right order*, and only when their inputs are ready.
3. **Reliability & recovery.** Data feeds fail, servers reboot, jobs crash. The system must detect failure, retry or alert, and **restart from where it stopped** — not from the beginning, and not silently.
4. **Continuity (24/7).** Continuous risk monitoring never stops. Time/cron triggers must keep firing whether or not anyone is watching.
5. **Reproducibility & auditability.** When an alert is issued, you must be able to show *exactly* which data, code, and steps produced it — for trust, for post-event review, and for accountability.
6. **Shared visibility.** More than the author needs to see status: the duty forecaster, the team lead, partner agencies, and management all need a live, honest view of "did it run, did it succeed, is it late?"

A pile of personal `cron` jobs meets **none** of these well. A workflow management system is designed to meet **all** of them.

---

## 3. What a workflow management system gives you

A WMS provides, as first-class built-in features, exactly the things you would otherwise re-invent (badly) in every script:

- **Scheduling** — start work at fixed times, on a cron pattern, or when a dependency completes. One clock for everything.
- **Dependencies** — express "B runs only after A completes" (and richer conditions) so the chain self-orders. No more `sleep 600 && run_next`.
- **Failure tolerance & restart** — a failed step is marked *aborted*, not ignored; the operator can fix and re-run just that step; after a crash the system restores its last known state and continues.
- **Monitoring** — a live tree of every step with its state (queued / active / complete / aborted), progress meters, labels, and events — visible to everyone, not just the author.
- **Resource control** — limits to avoid overwhelming a cluster or an API (e.g. "no more than 5 downloads at once").
- **Central definition** — the *whole* production chain is written down in one place as a versionable definition, not scattered across machines and crontabs.

The result: work that used to be a private, invisible script becomes a **published, monitored, recoverable operational service**.

---

## 4. From personal scripts to a published, team-wide operational setup

This is the organizational heart of the question: **how do you take the many workflows built by individuals and teams and turn them into one published setup that people beyond the team can monitor?**

A WMS gives you a natural progression:

**Stage 1 — Personal.** An analyst prototypes a product as a script/notebook on their own machine. Fine for development.

**Stage 2 — Defined as a workflow.** The steps are written as a *definition* (see §5) — named tasks, in families, under a suite, with explicit dependencies and a schedule. The logic is now readable by others and no longer tied to one laptop.

**Stage 3 — Published to the shared server.** The definition is loaded onto the **central WMS server**. Now it runs on shared, always-on infrastructure on a known schedule, and its status is visible in the shared monitor. Ownership can transfer; the author can go on leave.

**Stage 4 — Composed across teams.** Multiple teams' suites live on the same server. A downstream product (say, the published flood-risk dashboard) can *trigger on* the completion of upstream suites (the hazard forecast suite, the exposure-update suite) — even across teams — because everything is in one dependency-aware system. The end-to-end chain becomes explicit and enforceable.

**Stage 5 — Monitored by more than the team.** Because state lives on the central server and is exposed through a monitor UI and an API (see §6), the duty officer, the team lead, partner agencies, and management can all watch the same live picture — read-only if appropriate — without touching anyone's laptop. "Did today's product run and succeed?" becomes a glance at a dashboard, not a phone call.

This is the difference between a **collection of private automations** and a **published operational system**: shared infrastructure, explicit cross-team dependencies, transferable ownership, and open (role-appropriate) visibility.

---

## 5. How the pieces map (the node model)

Workflow systems organize work as a **tree of nodes**. In ecFlow specifically (the tool assessed in the companion document), the units are:

- **Suite** — a top-level workflow with its own schedule/clock. *Example:* `daily_flood_ibf`.
- **Family** — a group of steps inside a suite; can nest. *Example:* `ingest`, `process`, `publish`.
- **Task** — a single step that runs a job (a script, a container, a Cloud Run execution). **This is the unit that actually runs something.** *Example:* `fetch_rainfall_forecast`, `compute_impact`.

Steps carry **attributes**: `trigger` (dependency: run only when a condition holds), `time`/`cron` (when to run), `event`/`meter`/`label` (progress and status others can watch), and `limit` (resource throttling).

A small IBF example, read top to bottom:

```
suite daily_flood_ibf
  cron 02:00                          # run every day at 02:00
  family ingest
    task fetch_rainfall_forecast      # download today's forecast
    task fetch_river_levels           # download gauge observations
    task update_exposure_layers       # refresh population/assets
  family process
    trigger ingest == complete        # wait for ALL of ingest
    task compute_hazard
    task compute_impact
      trigger compute_hazard == complete
      meter progress 0 100            # publishes % done to the monitor
  family publish
    trigger process == complete
    task publish_dashboard            # push the decision-ready product
    task notify_partners
      event alert_issued              # others can watch this event
```

Every arrow of the hazard × exposure × vulnerability → impact chain becomes an explicit, monitored, ordered task. Each task can be a **Cloud Run job** (set the job command to launch it) rather than a local process — so the scheduler/timekeeper stays small while the heavy compute scales elastically (see the deployment topology in the companion doc).

---

## 6. Monitoring — how "more than the team" watches it

The reason a WMS enables broad oversight is that **status is centralized and exposed**, not trapped in logs on someone's machine:

- **A live status tree.** Every suite/family/task shows its state (queued, active, complete, aborted, suspended) in real time. A red (aborted) task is immediately visible to anyone watching.
- **Progress signals authored into the workflow.** `meter` (e.g. 0–100%), `label` (free text like "processing 2026-07-02 12Z"), and `event` (e.g. `alert_issued`) let the workflow *tell* observers what is happening in domain terms.
- **Lateness detection.** A `late` attribute flags a step that hasn't started or finished by its deadline — the single most useful signal for "will the 08:00 briefing have its product?"
- **A programmatic API.** State is available over a REST/JSON API, so dashboards, status pages, and partner systems can pull a read-only view — enabling monitoring by people well beyond the immediate team (management, partner agencies, a public status page).
- **Audit trail.** The system records what ran, when, and its outcome, so an issued alert can be traced back to its inputs and steps for post-event review and accountability.

Together these turn "is it working?" from tribal knowledge into a shared, honest, always-available picture.

---

## 7. Why this matters specifically for IBF and continuous risk monitoring

- **Lives and decisions depend on timeliness and reliability.** A missed or late flood-impact product is not a minor IT glitch; it can mean an un-warned community. The failure-tolerance, restart, and lateness features are not conveniences — they are the point.
- **The chain is inherently multi-team and multi-source.** Hazard, exposure, and vulnerability come from different specialists and different data feeds. Only a dependency-aware, centrally-defined system keeps that chain correct and ordered as it grows.
- **Continuous monitoring means never stopping.** Risk assessment runs on a cadence indefinitely. A system built to keep a schedule running 24/7, survive restarts, and be watched by a rotating duty roster is a fundamentally better fit than personal cron jobs.
- **Trust requires transparency.** IBF products inform official warnings. Being able to show, live and after the fact, that the right steps ran on the right data is essential to institutional trust — internally and with partners.
- **Scale and turnover.** As products multiply and staff change, the WMS is what lets the *organization* (not just individuals) own the operational capability.

---

## 8. In one paragraph

Impact-based forecasting and continuous risk monitoring are **operational production chains**, not one-off scripts: multi-step, multi-team, time-critical, and unending. A workflow management system is the shared backbone that defines those chains in one place, schedules and orders them, recovers them when things fail, and — crucially — **publishes their status so the whole organization and its partners can monitor them**, turning fragile personal automations into a trustworthy, transferable, observable operational service. That is why it is needed, and it is exactly what ecFlow (see the companion assessment) was built to do.
