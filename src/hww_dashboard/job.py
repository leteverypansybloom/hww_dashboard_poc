"""The scheduled job: ingest the workbooks, then build the tables.

``hww-run [config.toml]`` runs ``hww-ingest`` and, only if every file
loaded or was already loaded, ``hww-wrangle`` with the same config. If
ingestion fails (a quarantined or failed file, or an empty source
folder) the tables aren't rebuilt, so they keep the last complete,
consistent set, and the job exits with ingestion's code so the failure
shows.

For the pipeline to use what was just ingested, the config needs
``[landed] read = true``.
"""

import sys
from collections.abc import Sequence

from hww_dashboard import landing, wrangle

DEFAULT_CONFIG = "config.toml"


def main(argv: Sequence[str] | None = None) -> int:
    """Command line: ``hww-run [config.toml]``.

    Args:
        argv: Arguments (defaults to sys.argv[1:]).

    Returns:
        Ingestion's exit code if it failed, otherwise the pipeline's:
        0 when both finished.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    config = args[0] if args else DEFAULT_CONFIG
    code = landing.main([config])
    if code != 0:
        print(
            f"Ingestion exited with {code}; the tables were not rebuilt.",
            file=sys.stderr,
        )
        return code
    return wrangle.main([config])


if __name__ == "__main__":
    sys.exit(main())
