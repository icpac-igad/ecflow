"""Reusable task-script generators.

The container->host bridge (curl the executor) is factored out here so every real
stage reuses one contract; stubs share a second. `%%` is a literal percent for ecFlow;
`%RUN%` / `%RUN_DATE%` are ecFlow variable references."""


def bridge_script(executor: str, endpoint: str, timeout: int) -> str:
    return (
        'DATE="%RUN_DATE%"; [ -z "$DATE" ] && DATE=$(date -u +%%Y%%m%%d)\n'
        f'echo "stage {endpoint} - date ${{DATE}} - run %RUN%z"\n'
        f'curl -fsS --max-time {timeout} "{executor}/run/{endpoint}?date=${{DATE}}&run=%RUN%"\n'
    )


def stub_script(title: str) -> str:
    return f'echo "{title} - placeholder (Phase 3: real work pending)"\nsleep 1\n'
