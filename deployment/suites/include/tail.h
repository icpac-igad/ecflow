# Standard ecFlow job epilogue. Reports success and disarms the error trap.
wait
ecflow_client --complete
trap 0
exit 0
