# ecFlow runtime image.
#
# One image, three roles (server / http / udp) selected by the compose command.
# ecFlow is installed from conda-forge rather than built from source: the fork at
# icpac-igad/ecflow is ~300k lines of C++ and we are not modifying the engine, only
# operating it. Swap this for a source build only if an engine patch is ever needed.

FROM mambaorg/micromamba:2.0-ubuntu24.04

ARG ECFLOW_VERSION=5.18.0

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini procps \
 && rm -rf /var/lib/apt/lists/*

USER $MAMBA_USER
RUN micromamba install -y -n base -c conda-forge \
        ecflow=${ECFLOW_VERSION} \
        python=3.12 \
 && micromamba clean --all --yes

ARG MAMBA_DOCKERFILE_ACTIVATE=1
ENV PATH=/opt/conda/bin:$PATH

# ECF_HOME is the server's working directory: suite scripts, generated jobs, job
# output, the checkpoint (ecf.check/.b) and the log all live under it. It is bind
# mounted from the host so the state survives container replacement.
ENV ECF_HOME=/ecflow/home \
    ECF_PORT=3141 \
    ECF_HOST=ecflow-server

USER root
RUN mkdir -p /ecflow/home && chmod 0777 /ecflow /ecflow/home

# ecFlow refuses to run under a uid it cannot resolve to a name:
#   UserCmd::get_user: could not determine user name for uid <N>
# The container runs as the host's uid so bind-mounted state stays host-owned,
# and that uid has no /etc/passwd entry. Make passwd writable by group 0 (the
# standard arbitrary-uid pattern) so the entrypoint can add the missing entry
# at startup. Compose grants group 0 via group_add.
RUN chgrp 0 /etc/passwd && chmod g+w /etc/passwd
COPY --chown=$MAMBA_USER_ID:$MAMBA_USER_GID entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER $MAMBA_USER
WORKDIR /ecflow/home

# tini reaps the job processes the server forks; without it they become zombies.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["server"]
