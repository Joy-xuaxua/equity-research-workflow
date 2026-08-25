"""临时脚本：验证 adjudications 计划锚点在采集文件正文（剔除指标登记块）中出现且仅出现 1 次。"""
import json
import re
import sys

BASE = "C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825/collection/"


def extract_registry_block(text):
    m = re.search(r"^##\s*指标登记\s*$", text, flags=re.M)
    if not m:
        return None, text
    after = text[m.end():]
    fence = re.search(r"^```[a-zA-Z]*\s*$", after, flags=re.M)
    if not fence:
        return None, text
    start = fence.end()
    close = re.search(r"^```\s*$", after[start:], flags=re.M)
    if not close:
        return None, text
    block = after[start:start + close.start()]
    body = text[:m.end()] + after[:fence.end()] + after[start + close.end():]
    return block, body


plan = json.load(open(sys.argv[1], encoding="utf-8"))
cache = {}
bad = 0
for rec in plan:
    for fref in rec["files"]:
        fname = fref["file"]
        if fname not in cache:
            text = open(BASE + fname, encoding="utf-8").read()
            _, body = extract_registry_block(text)
            cache[fname] = body
        n = cache[fname].count(fref["anchor"])
        flag = "OK" if n == 1 else "!!"
        if n != 1:
            bad += 1
        print(f"{flag} {rec['id']} {fref['side']} {fname} count={n} anchor={fref['anchor'][:40]}")
print("BAD:", bad)
