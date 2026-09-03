"""PyInstaller 進入點。平常不用碰 —— 開發時仍是 `python -m jarvis`。"""

import sys

from jarvis.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
