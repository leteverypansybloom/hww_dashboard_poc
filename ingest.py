"""Land the HWW workbooks with py-common: ``python ingest.py [config.toml]``.

With no argument it uses the config.toml next to this file, wherever it
is run from. ``--stage FOLDER`` first copies the workbooks named in the
config from FOLDER into the local landing folder. The job itself is
:mod:`hww_dashboard.landing`.
"""

import sys
from pathlib import Path

from hww_dashboard.landing import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        default_config = Path(__file__).resolve().with_name("config.toml")
        args = [str(default_config), *args]
    sys.exit(main(args))
