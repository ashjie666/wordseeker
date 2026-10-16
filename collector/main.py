"""采集主流程：Google Trends → 计算 → 导出 web/data/*.json|js。

    python -m collector.main                # 默认窗口（realtime）
    python -m collector.main --window 7d    # 用近 7 天窗口出榜
    python -m collector.main --backend sample --no-cache
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request  # noqa: F401 - 保持与 backends 一致的网络栈引用习惯
from datetime import datetime, timedelta, timezone

from .backends import build_backend
from .emit import emit
from .scoring import breakout, build_board, latest, sparkline, today_summary
from .store import Cache, History

CST = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DATA = os.path.join(ROOT, "web", "data")
# 游戏对比图只保留这两个窗口：3 个窗口每次采集要多打一轮上游查询，而实时与 7 天
# 已能覆盖「当下热度」与「一周走势」两个最常看的粒度。
COMPARE_WINDOWS = ("realtime", "7d")


def log(message):
    print(message, flush=True)


def chunked(items, size):
    return [items[index:index + size] for index in range(0, len(items), size)]


def thin(series, target):
    """等距降采样，保留首尾与 [ts, value] 结构，用于前端折线图。"""
    if not series or len(series) <= target:
        return series
    step = (len(series) - 1) / (target - 1)
    return [series[int(round(index * step))] for index in range(target)]


def fetch_series(backend, cache, terms, geo, timeframe, use_cache=True, anchor=None, anchor_target=60.0):
    """按 batch 分批取序列，并用锚点词把各批次拉到同一标尺上。

    Google Trends 每次查询都会把该批词里的最高值归一化成 100，分批查询会得到互不可比的
    尺度。这里每批都额外带上一个锚点词（同批不超过 5 个），再按「锚点目标值 ÷ 锚点实测值」
    缩放整批结果 —— 这样才能把跨批次的热度拼成一张可比较的榜。
    """
    merged = {}
    size = int(backend.config["collect"]["batch_size"])
    if getattr(backend, "is_sample", False):
        anchor = None  # 示例数据本身就是绝对合成值，不需要（也不适合）锚点校准
    step = max(1, size - 1) if anchor else size
    for chunk in chunked(list(terms), step):
        query = list(chunk)
        if anchor and anchor not in query:
            query.append(anchor)
        key = Cache.series_key(query, geo, timeframe)
        payload = cache.get(key) if use_cache else None
        if payload is None:
            payload = backend.interest_over_time(query, geo, timeframe)
            cache.put(key, payload)
        points = payload.get("points") or {}

        if anchor and anchor in query:
            anchor_series = points.get(anchor) or []
            anchor_value = float(anchor_series[-1][1]) if anchor_series else 0.0
            scale = (float(anchor_target) / anchor_value) if anchor_value > 0 else 1.0
            for term in chunk:
                merged[term] = [[stamp, max(0.0, min(100.0, value * scale))]
                                for stamp, value in (points.get(term) or [])]
        else:
            for term in chunk:
                merged[term] = points.get(term) or []
    return merged


def fetch_related(backend, cache, term, geo, timeframe, use_cache=True):
    key = Cache.related_key(term, geo, timeframe)
    cached = cache.get(key) if use_cache else None
    if cached:
        return cached.get("points") or {}
    if not hasattr(backend, "related_queries"):
        return {}
    result = backend.related_queries(term, geo, timeframe)
    cache.put(key, result)
    return result.get("points") or {}


def links_for(term):
    """关联讨论入口。只拼搜索链接，不抓取任何内容，零隐私风险。"""
    query = urllib.parse.quote(term)
    return [
        {"label": "Google News", "url": f"https://news.google.com/search?q={query}&hl=en-US"},
        {"label": "Reddit 讨论", "url": f"https://www.reddit.com/search/?q={query}&sort=relevance&t=month"},
        {"label": "YouTube 视频", "url": f"https://www.youtube.com/results?search_query={query}"},
        {"label": "Google 网页搜索", "url": f"https://www.google.com/search?q={query}"},
    ]


def run(args):
    config_path = args.config or os.path.join(ROOT, "config.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    backend = build_backend(config, log, force=args.backend)
    sample_mode = bool(getattr(backend, "is_sample", False))
    cache = Cache(os.path.join(ROOT, "data", "cache"), config["collect"]["cache_ttl_hours"], log)
    history = History(os.path.join(ROOT, "data", "history.json"), log)
    previous = history.previous_values()

    keywords = config["keywords"]
    terms_all = [item["term"] for item in keywords]
    meta_map = {item["term"]: item for item in keywords}
    game_terms = [item["term"] for item in keywords if item.get("category") == "game"]
    regions = config["regions"]
    window_id = args.window if args.window in config["windows"] else config["default_window"]
    timeframe = config["windows"][window_id]["timeframe"]
    use_cache = not args.no_cache
    anchor_conf = config.get("anchor") or {}
    anchor = anchor_conf.get("term")
    anchor_target = float(anchor_conf.get("target") or 60)

    def fetch(terms, geo, timeframe):
        return fetch_series(backend, cache, terms, geo, timeframe, use_cache, anchor, anchor_target)

    # ---- 1) 主榜：每个地区各出一份完整词表 ----
    log(f"1/4 采集主榜（窗口 {config['windows'][window_id]['label']}）")
    boards, region_series, current_values = {}, {}, {}
    for region in regions:
        rid = region["id"]
        series_map = fetch(terms_all, region["geo"], timeframe)
        current_values[rid] = {term: latest(series_map.get(term) or []) for term in terms_all}
        region_series[rid] = series_map
        entries = [{"term": term,
                    "value": current_values[rid][term],
                    "spark": sparkline(series_map.get(term) or [])} for term in terms_all]
        boards[rid] = build_board(entries, (previous or {}).get(rid))
        log(f"    {region['label']}：{len(terms_all)} 词")

    # ---- 2) 飙升榜 ----
    log("2/4 计算飙升榜")
    breakout_by_region, breakout_all = {}, []
    for region in regions:
        items = breakout(region_series[region["id"]])
        for item in items:
            meta = meta_map.get(item["term"]) or {}
            item.update({"cn": meta.get("cn"), "category": meta.get("category"),
                         "game_type": meta.get("game_type"), "region": region["id"]})
        breakout_by_region[region["id"]] = items
        breakout_all.extend(items)
    breakout_all.sort(key=lambda item: -item["growth"])
    breakout_all = breakout_all[:60]

    # ---- 3) 游戏频道 ----
    log("3/4 采集游戏频道与对比序列")
    game_heat = {}
    for region in regions:
        rid = region["id"]
        entries = [{"term": term,
                    "value": current_values[rid].get(term, 0.0),
                    "spark": sparkline(region_series[rid].get(term) or [])} for term in game_terms]
        prev = (previous or {}).get(rid) or {}
        prev_games = {term: prev[term] for term in game_terms if term in prev}
        game_heat[rid] = build_board(entries, prev_games or None)

    compare = {}
    for wid in COMPARE_WINDOWS:
        # 主榜「全球」那一轮用的窗口正是 window_id，且覆盖了全部游戏词，所以同窗口直接复用，
        # 不再为对比图重复打一轮上游查询。
        if wid == window_id:
            series_map = region_series["world"]
        else:
            series_map = fetch(game_terms, "", config["windows"][wid]["timeframe"])
        for term in game_terms:
            compare.setdefault(term, {})[wid] = thin(series_map.get(term) or [], 40)

    game_breakout = {}
    for region in regions:
        rid = region["id"]
        subset = {term: region_series[rid].get(term) or [] for term in game_terms}
        items = breakout(subset, limit=10)
        for item in items:
            meta = meta_map.get(item["term"]) or {}
            item.update({"cn": meta.get("cn"), "category": "game",
                         "game_type": meta.get("game_type"), "region": rid})
        game_breakout[rid] = items

    # ---- 4) 详情页 ----
    log("4/4 采集详情序列与相关搜索")
    detail_terms = [row["t"] for row in boards["world"][: int(config["detail_max_terms"])]]
    for term in game_terms:
        if term not in detail_terms:
            detail_terms.append(term)

    detail_series = {term: {} for term in detail_terms}
    for wid in config["detail_windows"]:
        # 同窗口（实时）已在主榜「全球」那轮抓过全量词表，复用即可；其余窗口才真正发起查询。
        if wid == window_id:
            series_map = region_series["world"]
        else:
            series_map = fetch(detail_terms, "", config["windows"][wid]["timeframe"])
        for term in detail_terms:
            detail_series[term][wid] = thin(series_map.get(term) or [], 60)

    related = {}
    for term in detail_terms:
        points = fetch_related(backend, cache, term, "", timeframe, use_cache)
        related[term] = {"rising": points.get("rising") or [], "top": points.get("top") or []}

    detail_items = {}
    for term in detail_terms:
        meta = meta_map.get(term) or {}
        geo = []
        for region in regions:
            value = current_values[region["id"]].get(term)
            if value is None:
                continue
            geo.append({"id": region["id"], "label": region["label"],
                        "group": region["group"], "value": int(round(value))})
        detail_items[term] = {
            "term": term,
            "cn": meta.get("cn"),
            "category": meta.get("category"),
            "game_type": meta.get("game_type"),
            "studio": meta.get("studio"),
            "windows": {wid: detail_series[term].get(wid) or [] for wid in config["detail_windows"]},
            "geo": geo,
            "related": related[term],
            "links": links_for(term),
        }

    # ---- 汇总 meta 与三个数据文件 ----
    generated_at = datetime.now(timezone.utc)
    meta_block = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "generated_at_cst": generated_at.astimezone(CST).strftime("%Y-%m-%d %H:%M"),
        "timezone": "UTC",
        "data_mode": "sample" if sample_mode else "live",
        "backend": backend.name,
        "window": window_id,
        "metric": "Google Trends 相对热度指数（0-100，非绝对搜索量）",
        "note": ("本页为离线示例数据（未接入真实 Google Trends），仅用于演示界面与流程，不代表真实搜索热度。"
                 if sample_mode else
                 f"热度值以锚点词 {anchor}（定标 {anchor_target:g}）逐批校准后归一到 0-100，可在同地区内横向比较；不是绝对搜索量。"),
        "prev_snapshot_at": history.snapshots[-1]["at"] if history.snapshots else None,
    }

    trending = {
        "meta": meta_block,
        "site": config["site"],
        "categories": config["categories"],
        "regions": [{"id": r["id"], "label": r["label"], "group": r["group"]} for r in regions],
        "terms": {item["term"]: {key: item[key] for key in ("cn", "category", "game_type", "studio") if key in item}
                  for item in keywords},
        "boards": boards,
        "breakout": breakout_by_region,
        "breakout_all": breakout_all,
        "summary": today_summary(meta_map, boards["world"], game_heat["world"],
                                 breakout_by_region["world"], sample_mode),
    }

    game_index = {rid: {row["t"]: row for row in rows} for rid, rows in game_heat.items()}
    games = {
        "meta": meta_block,
        "game_types": config["game_types"],
        "regions": [{"id": r["id"], "label": r["label"], "group": r["group"],
                     "group_label": r.get("group_label")} for r in regions],
        "games": [{
            "term": term,
            "cn": (meta_map.get(term) or {}).get("cn"),
            "studio": (meta_map.get(term) or {}).get("studio"),
            "game_type": (meta_map.get(term) or {}).get("game_type"),
            "heat": {rid: game_index[rid].get(term) for rid in game_index},
        } for term in game_terms],
        "breakout": game_breakout,
        "compare": compare,
        "compare_windows": [{"id": wid, "label": config["windows"][wid]["label"]} for wid in COMPARE_WINDOWS],
    }

    series = {
        "meta": meta_block,
        "windows": [{"id": wid, "label": config["windows"][wid]["label"]} for wid in config["detail_windows"]],
        "items": detail_items,
    }

    if args.dry_run:
        log("dry-run：跳过写盘")
    else:
        emit(WEB_DATA, {"trending": trending, "games": games, "series": series}, log)

    history.append(meta_block["generated_at"], current_values)
    if not args.dry_run:
        history.save()

    top = boards["world"][:3]
    log("主榜前三：" + "，".join(f"{row['t']}({row['v']})" for row in top))
    if sample_mode:
        log("注意：本次为示例数据（未接入真实 Google Trends）。前端已标注为示例。")
    log("完成。")


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="collector.main", description="WordSeeker 采集器")
    parser.add_argument("--config", help="配置文件路径（默认项目根 config.json）")
    parser.add_argument("--window", help="榜单窗口：realtime / 7d / 30d / 90d")
    parser.add_argument("--backend", choices=["auto", "sample", "serpapi", "pytrends"], help="强制指定后端")
    parser.add_argument("--no-cache", action="store_true", help="忽略磁盘缓存，强制重新抓取")
    parser.add_argument("--dry-run", action="store_true", help="只跑流程，不写盘")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    log(f"WordSeeker 采集开始 {datetime.now(CST).strftime('%Y-%m-%d %H:%M')} (CST)")
    run(args)


if __name__ == "__main__":
    main()
