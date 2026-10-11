"""ตรวจสอบคลังข้อสอบ: python tools/validate_questions.py"""
import glob
import json
import os
import re
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDIR = os.path.join(BASE, "questions")
EXPECT = int(os.environ.get("EXPECT_PER_SUBJECT", "100"))
BAD_CHOICE = re.compile(r"(ถูกทุกข้อ|ทุกข้อ|ไม่มีข้อใดถูก|ข้อ\s*[กขคง]\s*(และ|,)\s*ข้อ?\s*[กขคง]|ถูกทั้ง|all of the above|none of the above)", re.I)

errors, warnings = [], []
subjects = defaultdict(list)
names = {}
seen_q = {}

for path in sorted(glob.glob(os.path.join(QDIR, "*.json"))):
    fn = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        errors.append(f"{fn}: JSON ผิดรูปแบบ - {e}")
        continue
    sid = data.get("subject_id")
    name = data.get("subject")
    if sid is None or not name:
        errors.append(f"{fn}: ขาด subject_id หรือ subject")
        continue
    if names.setdefault(sid, name) != name:
        errors.append(f"{fn}: ชื่อวิชาไม่ตรงกับไฟล์อื่นของวิชา {sid}")
    for i, q in enumerate(data.get("questions", []), 1):
        loc = f"{fn} #{i}"
        for key in ("q", "c", "a", "e"):
            if key not in q:
                errors.append(f"{loc}: ขาดคีย์ {key}")
        if "q" not in q or "c" not in q or "a" not in q:
            continue
        if not isinstance(q["c"], list) or len(q["c"]) != 4:
            errors.append(f"{loc}: ต้องมี 4 ตัวเลือก")
            continue
        if not isinstance(q["a"], int) or not 0 <= q["a"] <= 3:
            errors.append(f"{loc}: a ต้องเป็น 0-3")
            continue
        if len(set(c.strip() for c in q["c"])) != 4:
            errors.append(f"{loc}: มีตัวเลือกซ้ำกัน")
        for c in q["c"]:
            if not c.strip():
                errors.append(f"{loc}: ตัวเลือกว่าง")
            if BAD_CHOICE.search(c):
                errors.append(f"{loc}: ตัวเลือกอ้างอิงตัวเลือกอื่น/ทุกข้อ (สุ่มลำดับแล้วจะผิด): {c}")
        if not q.get("e", "").strip():
            errors.append(f"{loc}: ไม่มีคำอธิบายเฉลย")
        if re.search(r"\?\s", q.get("e", "")) and "V3?" in q.get("e", ""):
            errors.append(f"{loc}: คำอธิบายมีข้อความลังเล")
        key = re.sub(r"\s+", "", q["q"])
        if key in seen_q:
            errors.append(f"{loc}: โจทย์ซ้ำกับ {seen_q[key]}")
        seen_q[key] = loc
        subjects[sid].append(q)

print("=" * 60)
total_bad_len = 0
for sid in sorted(subjects):
    qs = subjects[sid]
    dist = Counter(q["a"] for q in qs)
    longest = sum(1 for q in qs if len(q["c"][q["a"]]) == max(len(c) for c in q["c"]))
    print(f"วิชา {sid}: {names[sid]}\n   จำนวน {len(qs)} ข้อ | เฉลย ก/ข/ค/ง = "
          f"{dist[0]}/{dist[1]}/{dist[2]}/{dist[3]} | คำตอบถูกเป็นข้อที่ยาวที่สุด {longest*100//max(len(qs),1)}%")
    if len(qs) < EXPECT:
        errors.append(f"วิชา {sid}: มี {len(qs)} ข้อ (ต้องการอย่างน้อย {EXPECT})")
    mx = max(dist.values()) / max(len(qs), 1)
    if mx > 0.4:
        warnings.append(f"วิชา {sid}: เฉลยกระจุกที่ตัวเลือกเดียว {mx*100:.0f}%")
print("=" * 60)
print(f"รวม {sum(len(v) for v in subjects.values())} ข้อ, {len(subjects)} วิชา")
for w in warnings:
    print("WARN :", w)
for e in errors:
    print("ERROR:", e)
print("ผลตรวจ:", "ผ่าน [OK]" if not errors else f"พบข้อผิดพลาด {len(errors)} รายการ")
sys.exit(1 if errors else 0)
