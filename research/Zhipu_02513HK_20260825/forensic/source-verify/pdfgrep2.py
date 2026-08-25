"""临时脚本 v2：按内容流顺序拼接 T1 字体字面字符串，重建设备文本后统计关键数字（回源核验用）。"""
import re
import sys
import zlib

path = sys.argv[1]
data = open(path, "rb").read()
out = []
for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
    try:
        d = zlib.decompress(m.group(1))
    except Exception:
        continue
    if b"Tj" not in d and b"TJ" not in d:
        continue
    # 拼接该流内所有字面字符串（按出现顺序），跨 Tm/Td 不断开（数字可能被微移位切分）
    parts = re.findall(rb"\((?:[^()\\]|\\.)*\)", d)
    s = b"".join(p[1:-1] for p in parts)
    out.append(s.decode("latin-1"))
text = "".join(out)
compact = re.sub(r"\s+", "", text)
print("joined_chars:", len(compact))
for pat in sys.argv[2:]:
    c = pat.encode("utf-8").decode("latin-1")
    print(repr(pat), "->", compact.count(c), "| nospace_count:", re.sub(r"[,\s]", "", compact).count(re.sub(r"[,\s]", "", c)))
