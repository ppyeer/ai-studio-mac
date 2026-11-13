#!/usr/bin/env python3
"""把 examples/series.json 里的示例系列（苏东坡 · 一生行迹、徐霞客 · 游记行迹）导入正在运行的 AI Studio。

    python3 scripts/import_examples.py [--url http://127.0.0.1:8001]
已有同名系列就跳过。只导入系列、分组、分集和镜头文字，不含任何成片。
"""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "series.json"


def call(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(base + "/api/tools/ai-studio" + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SystemExit(f"{method} {path} 失败：{exc.read().decode('utf-8', 'replace')}") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    base = parser.parse_args().url.rstrip("/")
    existing = {item["name"] for item in call(base, "GET", "").get("series", [])}
    for series in json.loads(EXAMPLES.read_text(encoding="utf-8"))["series"]:
        if series["name"] in existing:
            print("已存在，跳过：", series["name"])
            continue
        head = {key: series.get(key) for key in ("name", "category", "description", "style", "route", "pron", "seal")}
        head["groups"] = [{"name": group["name"], "note": group.get("note", "")} for group in series["groups"]]
        created = call(base, "POST", "/series", head)["series"]
        mapping = {old["id"]: new["id"] for old, new in zip(series["groups"], created["groups"])}
        episodes = [{**episode, "id": "", "group": mapping.get(episode.get("group"), "")} for episode in series["episodes"]]
        call(base, "PATCH", f"/series/{created['id']}", {"episodes": episodes})
        print(f"已导入：{series['name']}（{len(episodes)} 集）")


if __name__ == "__main__":
    main()
