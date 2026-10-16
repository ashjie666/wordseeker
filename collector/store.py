"""采集缓存与历史快照。

- Cache   按 (terms, geo, timeframe) 缓存原始时间序列，避免重复打 Google Trends
- History 逐次保存「各地区 × 各词条」的最新热度，供排名变化 / 飙升榜计算与复盘

两者都是采集期中间产物，落在项目根的 `data/` 下（CI 里用 actions/cache 在运行之间传递）。
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

CACHE_FORMAT = 1


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


class Cache:
    """磁盘缓存。同一批词在 TTL 内重复采集时直接复用，省请求也降低被限流的概率。"""

    def __init__(self, directory, ttl_hours, log=print):
        self.directory = directory
        self.ttl = timedelta(hours=float(ttl_hours))
        self.log = log
        os.makedirs(directory, exist_ok=True)

    @staticmethod
    def series_key(terms, geo, timeframe):
        return json.dumps(["series", sorted(terms), geo, timeframe], ensure_ascii=False)

    @staticmethod
    def related_key(term, geo, timeframe):
        return json.dumps(["related", term, geo, timeframe], ensure_ascii=False)

    def _path(self, key):
        return os.path.join(self.directory, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key):
        payload = read_json(self._path(key))
        if not payload or payload.get("format") != CACHE_FORMAT:
            return None
        fetched = datetime.strptime(payload["fetched_at"], "%Y-%m-%dT%H:%M:%S%z")
        if datetime.now(timezone.utc) - fetched > self.ttl:
            return None
        return payload

    def put(self, key, result):
        record = dict(result)
        record.update({
            "format": CACHE_FORMAT,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "key": key,
        })
        write_json(self._path(key), record)


class History:
    """历史快照栈。每条快照只存「地区 → 词条 → 最新热度」，体积极小。"""

    LIMIT = 240

    def __init__(self, path, log=print):
        self.path = path
        self.log = log
        payload = read_json(path) or {}
        self.snapshots = payload.get("snapshots") or []

    def append(self, at, values):
        self.snapshots.append({"at": at, "values": values})
        if len(self.snapshots) > self.LIMIT:
            self.snapshots = self.snapshots[-self.LIMIT:]

    def previous_values(self):
        """上一条快照的 values；只有一条时返回 None。"""
        if len(self.snapshots) < 2:
            return None
        return self.snapshots[-2]["values"]

    def current_values(self):
        return self.snapshots[-1]["values"] if self.snapshots else None

    def save(self):
        write_json(self.path, {"snapshots": self.snapshots})
