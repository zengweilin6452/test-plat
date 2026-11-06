
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
src = (ROOT / "docs/platform-prototype/schema.sql").read_text(encoding="utf-8")
lines = src.splitlines()

tables = []
i = 0
while i < len(lines):
    m = re.match(r"^CREATE TABLE (\w+) \($", lines[i])
    if m:
        j = i + 1
        body = []
        while j < len(lines) and lines[j] != ");":
            body.append(lines[j].strip())
            j += 1
        tables.append({"name": m.group(1), "body": [b.rstrip(",") if b.endswith(",") else b for b in body], "line": i + 1})
        i = j
    i += 1

tcom = {}
ccom = []
for l in lines:
    m = re.match(r"^COMMENT ON TABLE (\w+) IS '(.*)';$", l)
    if m:
        tcom[m.group(1)] = m.group(2)
    m = re.match(r"^COMMENT ON COLUMN (\w+)\.(\w+) IS '(.*)';$", l)
    if m:
        ccom.append([m.group(1), m.group(2), m.group(3)])

idx = []
for l in lines:
    m = re.match(r"^CREATE (UNIQUE )?INDEX (\w+) ON (\w+) \(([^)]*)\)(?: WHERE (.*))?;$", l)
    if m:
        idx.append({
            "unique": bool(m.group(1)),
            "name": m.group(2),
            "table": m.group(3),
            "cols": m.group(4),
            "where": m.group(5),
        })

out = {"tables": tables, "table_comments": tcom, "column_comments": ccom, "indexes": idx}
p = pathlib.Path(__file__).resolve().parent / "parsed.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("root", ROOT)
print("tables", len(tables), "tcom", len(tcom), "ccom", len(ccom), "idx", len(idx))
