"""Google Trends 采集后端。

三个后端，统一接口 `interest_over_time(terms, geo, timeframe)`：

- SerpApiBackend  调 SerpApi 的 google_trends 引擎（无需代理，最稳，需 SERPAPI_KEY）
- PytrendsBackend 走 pytrends（免费，易被 Google 限流，需代理 + 请求间隔）
- SampleBackend   离线确定性合成数据（无 key / 无网络 / CI 演练用），产出带 data_mode=sample 标记

返回值统一为：

    {"backend": "<name>", "points": {"<term>": [["2026-10-17T05:00:00+00:00", 62], ...]}}
"""

import hashlib
import json
import math
import os
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# timeframe -> (采样点数, 每点小时数)，仅 SampleBackend 用于伪造分辨率的形状
_TIMEFRAME_SHAPE = {
    "now 1-H": (60, 1 / 60),
    "now 1-d": (24, 1),
    "now 7-d": (56, 3),
    "today 1-m": (30, 24),
    "today 3-m": (90, 24),
    "today 12-m": (52, 168),
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _seed(*parts) -> int:
    """跨进程稳定的确定性种子（Python 内置 hash 有随机化，不能用）。"""
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return int(hashlib.md5(raw).hexdigest()[:12], 16)


class SampleBackend:
    """离线示例数据：确定性合成，形状接近真实 Trends（季节性 + 趋势 + 噪声 + 地域偏好）。

    产出数据在前端会被明确标注为「示例数据」，不得当作真实热度解读。
    """

    name = "sample"
    is_sample = True

    # 各地区的整体活跃倍率，让「日韩」「东南亚」的排行不至于和「全球」完全雷同
    _GROUP_BIAS = {
        "global": 1.0, "na": 1.0, "eu": 0.94, "jp": 0.97,
        "sea": 1.06, "sa": 1.1, "latam": 1.04,
    }
    # 类别 × 地区的偏好矩阵：某类别在某地区更火（如二次元在日韩、SLG 在北美/欧洲）
    _CATEGORY_BIAS = {
        "game": {"global": 1.0, "na": 1.05, "eu": 0.95, "jp": 1.25, "sea": 1.3, "sa": 1.15, "latam": 1.1},
        "travel": {"global": 1.0, "na": 0.95, "eu": 1.0, "jp": 0.8, "sea": 1.35, "sa": 1.2, "latam": 0.9},
        "culture": {"global": 1.0, "na": 0.9, "eu": 0.95, "jp": 1.1, "sea": 1.3, "sa": 0.9, "latam": 0.85},
        "tech": {"global": 1.0, "na": 1.15, "eu": 1.05, "jp": 1.0, "sea": 1.1, "sa": 1.35, "latam": 1.05},
        "life": {"global": 1.0, "na": 1.0, "eu": 0.95, "jp": 0.85, "sea": 1.25, "sa": 1.0, "latam": 1.1},
    }

    def __init__(self, config, log=print):
        self.config = config
        self.log = log
        self._index = {item["term"]: item for item in config["keywords"]}
        self._region_group = {r["geo"] or "WORLD": r["group"] for r in config["regions"]}
        # WORDSAMPLE_SHIFT 把整个时间轴平移若干小时，便于造出"上一期"快照来演示趋势变化
        self._shift = float(os.environ.get("WORDSAMPLE_SHIFT", "0") or 0)

    def interest_over_time(self, terms, geo, timeframe):
        shape = _TIMEFRAME_SHAPE.get(timeframe, (24, 1))
        count, step_hours = shape
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=self._shift)
        # 小时窗口按小时滚动、日窗口按天滚动：让示例数据也有真实涨跌，而不是恒定不动
        bucket = now.strftime("%Y%m%d%H") if step_hours <= 1 else now.strftime("%Y%m%d")
        group = self._region_group.get(geo or "WORLD", "global")
        points = {}
        for term in terms:
            meta = self._index.get(term) or {}
            category = meta.get("category", "life")
            rng = random.Random(_seed(term, geo, timeframe))
            drift = rng.uniform(0.70, 1.30)          # 词条个体差异
            slope = rng.uniform(-0.45, 0.75)          # 窗口内涨跌
            phase = rng.uniform(0, math.tau)
            base = 26 + 54 * rng.random()              # 26..80，配合下方软饱和避免大量词触顶并列
            bias = self._GROUP_BIAS.get(group, 1.0) * self._CATEGORY_BIAS.get(category, {}).get(group, 1.0)
            series = []
            for i in range(count):
                ts = now - timedelta(hours=step_hours * (count - 1 - i))
                seasonal = 1 + 0.17 * math.sin(math.tau * i / max(8, count / 2.0) + phase)
                trend = 1 + slope * ((i / max(1, count - 1)) - 0.5)
                noise = 1 + 0.055 * (rng.random() - 0.5) * 2
                raw = base * bias * drift * seasonal * trend * noise
                # 软饱和压缩到 0-100，保证各词拉开差距，不出现大批并列的 100
                value = 100.0 * (1.0 - math.exp(-raw / 74.0))
                series.append([_iso(ts), round(max(1.0, value), 2)])
            points[term] = series
        return {"backend": self.name, "points": points}

    # 相关搜索词的常见修饰后缀，用来合成 rising 榜
    _SUFFIXES = ["news", "release date", "gameplay", "trailer", "update", "review",
                 "guide", "wiki", "vs", "worth it", "2026", "live"]

    def related_queries(self, term, geo, timeframe):
        meta = self._index.get(term) or {}
        category = meta.get("category", "life")
        rng = random.Random(_seed("related", term, geo, timeframe))
        peers = [item["term"] for item in self.config["keywords"]
                 if item.get("category") == category and item["term"] != term]
        random.Random(_seed("peers", term, geo)).shuffle(peers)

        top = [{"query": term, "value": 100}]
        for index, peer in enumerate(peers[:8], start=2):
            top.append({"query": peer, "value": max(8, int(96 / index))})

        rising = []
        for suffix in rng.sample(self._SUFFIXES, min(6, len(self._SUFFIXES))):
            rising.append({"query": f"{term} {suffix}", "value": int(rng.randint(120, 480))})
        return {"backend": self.name, "points": {"rising": rising, "top": top}}


class SerpApiBackend:
    """SerpApi google_trends 引擎。海外服务器直连，不依赖代理，适合放在 CI 里跑。"""

    name = "serpapi"
    is_sample = False
    _ENDPOINT = "https://serpapi.com/search.json"

    def __init__(self, api_key, config, log=print):
        self.api_key = api_key
        self.config = config
        self.log = log
        self._interval = float(config["collect"]["min_interval_sec"])
        self._last_call = 0.0

    def _throttle(self):
        wait = self._interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _request(self, params):
        url = self._ENDPOINT + "?" + urllib.parse.urlencode(params)
        for attempt in range(1, int(self.config["collect"]["max_retries"]) + 1):
            self._throttle()
            try:
                request = urllib.request.Request(url, headers={"User-Agent": self.config["collect"]["user_agent"]})
                with urllib.request.urlopen(request, timeout=45) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - 网络异常一律重试，超过上限再抛出
                self.log(f"  serpapi 第 {attempt} 次失败: {exc}")
                if attempt >= int(self.config["collect"]["max_retries"]):
                    raise
                time.sleep(float(self.config["collect"]["retry_backoff_sec"]) * attempt)
        return {}

    def related_queries(self, term, geo, timeframe):
        params = {
            "engine": "google_trends",
            "q": term,
            "date": timeframe,
            "data_type": "RELATED_QUERIES",
            "hl": "en",
            "api_key": self.api_key,
        }
        if geo:
            params["geo"] = geo
        related = (self._request(params) or {}).get("related_queries") or {}

        def pack(rows, fallback_rank=False):
            out = []
            for index, item in enumerate(rows or []):
                if not isinstance(item, dict) or not item.get("query"):
                    continue
                value = item.get("extracted_value")
                if value is None and fallback_rank:
                    value = max(1, 100 - index * 3)
                out.append({"query": item["query"], "value": int(value) if value is not None else None})
            return out[:20]

        return {"backend": self.name, "points": {
            "rising": pack(related.get("rising")),
            "top": pack(related.get("top"), fallback_rank=True),
        }}

    def interest_over_time(self, terms, geo, timeframe):
        params = {
            "engine": "google_trends",
            "q": ",".join(terms),
            "date": timeframe,
            "data_type": "TIMESERIES",
            "hl": "en",
            "api_key": self.api_key,
        }
        if geo:
            params["geo"] = geo
        timeline = self._request(params).get("interest_over_time", {}).get("timeline_data", [])
        points = {term: [] for term in terms}
        for slot in timeline:
            ts = slot.get("timestamp")
            if ts is None:
                continue
            stamp = _iso(datetime.fromtimestamp(int(ts), tz=timezone.utc))
            for value in slot.get("values", []):
                term = value.get("query")
                if term in points and value.get("extracted_value") is not None:
                    points[term].append([stamp, int(value["extracted_value"])])
        return {"backend": self.name, "points": points}


class PytrendsBackend:
    """pytrends 后端：免费但容易被 Google 限流，务必配代理与间隔（config.collect.proxies）。"""

    name = "pytrends"
    is_sample = False

    def __init__(self, config, log=print):
        from pytrends.request import TrendReq  # 懒导入：没装 pytrends 时不影响其他后端

        self.config = config
        self.log = log
        # pytrends 的 proxies 只接受 '' / str / dict 列表；传 None 会在 GetGoogleCookie
        # 的 len(self.proxies) 处抛 TypeError，被 auto 模式当成「pytrends 不可用」而退回
        # 示例后端（CI 上实测过一次）。所以没有代理时干脆不传这个参数。
        #
        # retries / backoff_factor 也不能传：一旦传了，pytrends 内部的 _get_data 会构造
        # urllib3 的 Retry(method_whitelist=...)，而该参数在 urllib3 2.x 已被移除
        # (TypeError: unexpected keyword argument 'method_whitelist')。重试改由 _fetch 负责。
        proxies = config["collect"].get("proxies") or ""
        client_kwargs = {"hl": "en-US", "tz": 0, "timeout": (10, 45)}
        if proxies:
            client_kwargs["proxies"] = proxies
        self._client = TrendReq(**client_kwargs)
        self._interval = float(config["collect"]["min_interval_sec"])
        self._batch = int(config["collect"]["batch_size"])
        self._last_call = 0.0

    def _throttle(self):
        wait = self._interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _fetch(self, call):
        """带节奏控制与重试地执行一次 pytrends 调用。

        pytrends 自带的重试依赖 urllib3 1.x 的参数，在 2.x 上会直接抛异常，
        所以这里自己重试：每次调用前先过 _throttle，失败按 retry_backoff_sec 递增等待。
        """
        attempts = int(self.config["collect"]["max_retries"])
        backoff = float(self.config["collect"]["retry_backoff_sec"])
        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                return call()
            except Exception as exc:  # noqa: BLE001 - 限流 / 网络异常一律重试，超过上限再抛出
                self.log(f"  pytrends 第 {attempt} 次失败: {exc}")
                if attempt >= attempts:
                    raise
                time.sleep(backoff * attempt)
        return None

    def interest_over_time(self, terms, geo, timeframe):
        points = {term: [] for term in terms}
        for start in range(0, len(terms), self._batch):
            chunk = terms[start:start + self._batch]

            def _query(chunk=chunk):
                self._client.build_payload(chunk, cat=0, timeframe=timeframe, geo=geo)
                return self._client.interest_over_time()

            frame = self._fetch(_query)
            if frame is None or frame.empty:
                continue
            for term in chunk:
                if term not in frame.columns:
                    continue
                for stamp, value in frame[term].items():
                    points[term].append([_iso(stamp.to_pydatetime()), int(value)])
        return {"backend": self.name, "points": points}

    def related_queries(self, term, geo, timeframe):
        """pytrends 的 rising 榜拿不到数值（Google 已移除），value 给 null，前端按无值渲染。"""

        def _query():
            self._client.build_payload([term], cat=0, timeframe=timeframe, geo=geo)
            return self._client.related_queries()

        block = (self._fetch(_query) or {}).get(term) or {}

        def pack(frame, fallback_rank):
            if frame is None or getattr(frame, "empty", True):
                return []
            out = []
            for index, (_, row) in enumerate(frame.iterrows()):
                if fallback_rank and index < 20:
                    out.append({"query": str(row.get("query")), "value": max(1, 100 - index * 3)})
                else:
                    out.append({"query": str(row.get("query")), "value": None})
            return out[:20]

        return {"backend": self.name, "points": {
            "rising": pack(block.get("rising"), False),
            "top": pack(block.get("top"), True),
        }}


def build_backend(config, log=print, force=None):
    """按 config.collect.backend 选择后端；auto 的优先级：SerpApi → pytrends → sample。"""
    import os

    choice = (force or config["collect"].get("backend") or "auto").lower()
    key = os.environ.get("SERPAPI_KEY", "").strip()

    if choice in ("auto", "serpapi") and key:
        log("采集后端: SerpApi")
        return SerpApiBackend(key, config, log)
    if choice == "serpapi":
        raise RuntimeError("config 指定 serpapi，但环境变量 SERPAPI_KEY 未设置")
    if choice in ("auto", "pytrends"):
        try:
            backend = PytrendsBackend(config, log)
            log("采集后端: pytrends")
            return backend
        except Exception as exc:  # noqa: BLE001 - pytrends 不可用时退回示例后端
            if choice == "pytrends":
                raise
            log(f"pytrends 不可用（{exc}），退回示例数据后端")
    log("采集后端: sample（离线示例数据，前端会标注为示例）")
    return SampleBackend(config, log)
