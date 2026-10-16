"""排名、变化与飙升榜计算。

输入是「时间序列」的原始形态（backend 返回的 points），输出是前端直接可用的小对象，
刻意压扁字段名（t/v/d/p/s）以控制榜单数据的体积。
"""

BREAKOUT_MIN_GROWTH = 25.0   # 飙升门槛：窗口内涨幅（%）
BREAKOUT_MIN_VALUE = 12.0    # 飙升门槛：当前热度下限，挡掉长尾噪声
BREAKOUT_LIMIT = 20


def latest(series):
    """窗口内的最后一个采样点，作为「当前热度」。"""
    return float(series[-1][1]) if series else 0.0


def sparkline(series, buckets=12):
    """把长序列降采样成 12 个点，供表格里的迷你走势图使用。"""
    values = [float(v) for _, v in series]
    if not values:
        return []
    if len(values) <= buckets:
        return [int(round(v)) for v in values]
    step = len(values) / buckets
    out = []
    for index in range(buckets):
        start = int(index * step)
        end = max(start + 1, int((index + 1) * step))
        chunk = values[start:end]
        out.append(int(round(sum(chunk) / len(chunk))))
    return out


def ranks(values_map):
    """热度降序 → {词条: 名次}。热度相同时按词条名排序，保证排名稳定可复现。"""
    ordered = sorted(values_map.items(), key=lambda kv: (-kv[1], kv[0]))
    return {term: index + 1 for index, (term, _) in enumerate(ordered)}


def build_board(entries, previous_values):
    """把某地区的词表整理成排行数组。

    entries: [{"term":..., "value":..., "spark":[...]}]，未排序
    previous_values: 上一条快照里该地区的 {词条: 热度}，没有则传 None
    """
    ordered = sorted(entries, key=lambda item: (-item["value"], item["term"]))
    prev_ranks = ranks(previous_values) if previous_values else None
    board = []
    for index, item in enumerate(ordered):
        term = item["term"]
        value = item["value"]
        row = {"t": term, "v": int(round(value)), "s": item["spark"]}
        if prev_ranks and term in prev_ranks:
            prev_value = float(previous_values[term])
            row["d"] = prev_ranks[term] - (index + 1)          # 正数=名次上升
            row["p"] = round((value - prev_value) / prev_value * 100, 1) if prev_value > 0 else 0.0
        else:
            row["d"] = None
            row["p"] = None
        board.append(row)
    return board


def breakout(series_map, limit=BREAKOUT_LIMIT):
    """飙升榜：窗口内涨幅最大且当前热度达标的词。

    growth 用「窗口后半段均值 ÷ 前半段均值」衡量，比首尾两点比值更能反映加速；
    同时保留首尾涨幅 head_growth 供前端展示。
    """
    scored = []
    for term, series in series_map.items():
        values = [float(v) for _, v in series]
        if len(values) < 4:
            continue
        current = values[-1]
        head = values[0]
        if current < BREAKOUT_MIN_VALUE:
            continue
        half = len(values) // 2
        early = sum(values[:half]) / max(1, half)
        late = sum(values[half:]) / max(1, len(values) - half)
        if early <= 0:
            continue
        growth = (late - early) / early * 100
        head_growth = (current - head) / head * 100 if head > 0 else 0.0
        if growth < BREAKOUT_MIN_GROWTH:
            continue
        scored.append({
            "term": term,
            "current": int(round(current)),
            "growth": round(growth, 1),
            "head_growth": round(head_growth, 1),
            "spark": sparkline(series, 10),
        })
    scored.sort(key=lambda item: -item["growth"])
    return scored[:limit]


def today_summary(meta_map, global_board, game_board, global_breakout, sample_mode):
    """底部「今日最热话题」的一句话摘要。纯模板拼装，不依赖任何外部模型。"""
    parts = []

    def label(term):
        entry = meta_map.get(term) or {}
        cn = entry.get("cn")
        return f"{term}（{cn}）" if cn else term

    if global_board:
        top = global_board[0]
        change = top.get("d")
        trend = ""
        if change is None:
            trend = ""
        elif change > 0:
            trend = f"，较上期上升 {change} 位"
        elif change < 0:
            trend = f"，较上期下降 {abs(change)} 位"
        else:
            trend = "，排名与上期持平"
        category = (meta_map.get(top["t"]) or {}).get("category", "other")
        category_cn = {"game": "游戏", "travel": "旅游", "culture": "文化", "tech": "科技", "life": "生活"}.get(category, "其他")
        parts.append(f"全球榜由 {label(top['t'])} 领跑（{category_cn}，热度 {top['v']}{trend}）")

    if game_board:
        top = game_board[0]
        parts.append(f"游戏频道头部是 {label(top['t'])}（热度 {top['v']}）")

    if global_breakout:
        top = global_breakout[0]
        parts.append(f"飙升最快的是 {label(top['term'])}，窗口内加速 {top['growth']}%")

    if not parts:
        return "本期暂无足够数据生成摘要。"

    head = "今日海外搜索中国相关关键字的最热话题："
    tail = "。数据为 Google Trends 相对热度指数（0-100），非绝对搜索量。"
    if sample_mode:
        tail = "。当前为示例数据（未接入真实 Trends），接入 SerpApi 或 pytrends 后自动切换。"
    return head + "；".join(parts) + tail
