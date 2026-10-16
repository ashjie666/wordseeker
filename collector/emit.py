"""把采集结果导出成前端直接消费的静态数据 —— json 与 js 双份。

- `.json` 给服务器环境用（fetch）
- `.js` 给 file:// 本地预览用（内联成 window 全局变量，绕开 file:// 的 CORS 限制）
"""

import json
import os

from .store import write_json

JS_GLOBALS = {
    "trending": "WS_TRENDING",
    "games": "WS_GAMES",
    "series": "WS_SERIES",
}


def emit(directory, payloads, log=print):
    os.makedirs(directory, exist_ok=True)
    written = []
    for name, payload in payloads.items():
        json_path = os.path.join(directory, name + ".json")
        write_json(json_path, payload)
        written.append(json_path)

        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        js_path = os.path.join(directory, name + ".js")
        with open(js_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(f"window.{JS_GLOBALS.get(name, 'WS_DATA')} = {text};\n")
        written.append(js_path)
    log(f"导出 {len(payloads)} 份数据 → {directory}")
    return written
