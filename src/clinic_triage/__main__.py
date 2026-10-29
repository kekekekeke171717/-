"""允许 `python -m clinic_triage <子命令>` 直接跑。

等价于 python -m clinic_triage.main，写起来短一点。
"""
from __future__ import annotations

from clinic_triage.main import main

if __name__ == "__main__":
    raise SystemExit(main())
