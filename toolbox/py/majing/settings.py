# -*- coding: utf-8 -*-
import json
import os


def _path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


class Settings:
    """很小的 JSON 设置文件；读写失败都不影响程序。"""

    def __init__(self):
        self.data = {}
        try:
            with open(_path(), encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            pass

    def get(self, k, default=None):
        return self.data.get(k, default)

    def set(self, k, v):
        self.data[k] = v
        try:
            with open(_path(), "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass


settings = Settings()
