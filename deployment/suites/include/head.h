#!/usr/bin/env bash
# ^ MUST be line 1. ecFlow concatenates this file verbatim into the generated
# .job file, so anything above the shebang makes the kernel fall back to /bin/sh
# (dash), and `set -o pipefail` then fails with "Illegal option -o pipefail".
#
# Standard ecFlow job preamble, included at the top of every .ecf script.
# It tells the server the job has started (--init) and installs traps so any
# failure or signal reports back as --abort instead of leaving the task stuck
# "active" forever. Without this the engine cannot tell a crashed job from a
# slow one.
set -euxo pipefail

export ECF_PORT=%ECF_PORT%
export ECF_HOST=%ECF_HOST%
export ECF_NAME=%ECF_NAME%
export ECF_PASS=%ECF_PASS%
export ECF_TRYNO=%ECF_TRYNO%
export ECF_RID=$$

ERROR() {
  set +e
  wait
  ecflow_client --abort=trap
  trap 0
  exit 0
}
trap ERROR 0
trap '{ echo "Signal received"; ERROR; }' 1 2 3 4 5 6 7 8 10 12 13 15

ecflow_client --init="$$"
