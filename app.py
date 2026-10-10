"""เว็บฝึกทำข้อสอบการพยาบาล - Backend (Flask + SQLite)

รันในเครื่อง:   python app.py
รันบนเซิร์ฟเวอร์: gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT app:app

ตัวแปรสภาพแวดล้อม (Environment variables):
  DATA_DIR           โฟลเดอร์เก็บฐานข้อมูล (ค่าเริ่มต้น ./data) -> บน Render ให้ชี้ไปที่ Persistent Disk
  ADMIN_USERNAME     ชื่อผู้ใช้แอดมินเริ่มต้น (ค่าเริ่มต้น admin)
  ADMIN_PASSWORD     รหัสผ่านแอดมินเริ่มต้น (ถ้าไม่ตั้ง ระบบสุ่มให้และพิมพ์ใน log ครั้งแรก)
  COOKIE_SECURE      1 = ส่ง cookie เฉพาะ HTTPS (แนะนำเมื่อขึ้นอินเทอร์เน็ต)
  SESSION_TIMEOUT    วินาทีที่ถือว่า session ว่าง/หลุด (ค่าเริ่มต้น 120)
  PER_SUBJECT        จำนวนข้อที่สุ่มต่อวิชา (ค่าเริ่มต้น 30)
  PASS_PERCENT       เกณฑ์ผ่าน % (ค่าเริ่มต้น 70)
"""
import csv
import glob
import io
import json
import os
import random
import re
import secrets
import sqlite3
import time
from functools import wraps

from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "nursing.db")
QUESTIONS_DIR = os.environ.get("QUESTIONS_DIR", os.path.join(BASE_DIR, "questions"))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "120"))
PER_SUBJECT = int(os.environ.get("PER_SUBJECT", "30"))
PASS_PERCENT = float(os.environ.get("PASS_PERCENT", "70"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
MIN_PASSWORD_LEN = 6
PW_METHOD = "pbkdf2:sha256"

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config["JSON_AS_ASCII"] = False
app.json.ensure_ascii = False


# --------------------------------------------------------------------------- #
# คลังข้อสอบ (โหลดจากไฟล์ JSON ตอนเริ่มระบบ)
# --------------------------------------------------------------------------- #
SUBJECTS = {}   # subject_id -> {"id", "name", "ids": [question ids]}
QUESTIONS = {}  # question id -> dict


def load_questions():
    SUBJECTS.clear()
    QUESTIONS.clear()
    for path in sorted(glob.glob(os.path.join(QUESTIONS_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        sid = int(data["subject_id"])
        subj = SUBJECTS.setdefault(sid, {"id": sid, "name": data["subject"], "ids": []})
        for i, item in enumerate(data["questions"], start=len(subj["ids"]) + 1):
            qid = item.get("id") or f"{sid}-{i:03d}"
            QUESTIONS[qid] = {
                "id": qid,
                "subject_id": sid,
                "q": item["q"],
                "c": item["c"],
                "a": int(item["a"]),
                "e": item.get("e", ""),
            }
            subj["ids"].append(qid)


# --------------------------------------------------------------------------- #
# ฐานข้อมูล
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL,
    ip TEXT
);
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','submitted')),
    started_at REAL NOT NULL,
    submitted_at REAL,
    score INTEGER,
    total INTEGER NOT NULL,
    percent REAL,
    passed INTEGER
);
CREATE INDEX IF NOT EXISTS idx_exams_user ON exams(user_id);
CREATE TABLE IF NOT EXISTS exam_items (
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    pos INTEGER NOT NULL,
    q_id TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    perm TEXT NOT NULL,
    chosen INTEGER,
    flagged INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (exam_id, pos)
);
CREATE TABLE IF NOT EXISTS exam_subject_scores (
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    total INTEGER NOT NULL,
    PRIMARY KEY (exam_id, subject_id)
);
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    row = con.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin'").fetchone()
    if row["n"] == 0:
        username = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD")
        generated = password is None
        if generated:
            password = secrets.token_urlsafe(9)
        con.execute(
            "INSERT INTO users (username, display_name, password_hash, role, active,"
            " must_change_password, created_at) VALUES (?,?,?,?,1,?,?)",
            (username, "ผู้ดูแลระบบ", generate_password_hash(password, method=PW_METHOD),
             "admin", 1 if generated else 0, time.time()),
        )
        if generated:
            print("=" * 60)
            print(f"[SETUP] สร้างแอดมินเริ่มต้น  username: {username}  password: {password}")
            print("[SETUP] กรุณาเปลี่ยนรหัสผ่านหลังเข้าสู่ระบบครั้งแรก")
            print("=" * 60, flush=True)
    con.close()


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #
def err(message, code=400):
    return jsonify({"error": message}), code


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def user_dict(u):
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"] or u["username"],
        "role": u["role"],
        "must_change_password": bool(u["must_change_password"]),
    }


def get_session_user():
    """คืนข้อมูลผู้ใช้จาก cookie และต่ออายุ session ถ้ายังไม่หมดอายุ"""
    token = request.cookies.get("sid")
    if not token:
        return None
    con = db()
    row = con.execute(
        "SELECT s.token AS s_token, s.last_seen AS s_last_seen, u.* FROM sessions s"
        " JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    now = time.time()
    if now - row["s_last_seen"] > SESSION_TIMEOUT or not row["active"]:
        con.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    if now - row["s_last_seen"] > 3:
        con.execute("UPDATE sessions SET last_seen = ? WHERE token = ?", (now, token))
    return row


def login_required(admin=False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            u = get_session_user()
            if u is None:
                return err("กรุณาเข้าสู่ระบบ (หรือ session หมดอายุ)", 401)
            if admin and u["role"] != "admin":
                return err("ไม่มีสิทธิ์เข้าถึง", 403)
            g.user = u
            return fn(*args, **kwargs)
        return wrapper
    return deco


# จำกัดการเดารหัสผ่าน: ผิด 5 ครั้งภายใน 10 นาที -> ล็อก 5 นาที
FAILS = {}
MAX_FAILS, FAIL_WINDOW, LOCK_SECONDS = 5, 600, 300


def locked_seconds(key):
    rec = FAILS.get(key)
    if rec and rec["lock_until"] > time.time():
        return int(rec["lock_until"] - time.time()) + 1
    return 0


def record_fail(key):
    now = time.time()
    rec = FAILS.get(key)
    if not rec or now - rec["first"] > FAIL_WINDOW:
        rec = {"count": 0, "first": now, "lock_until": 0}
    rec["count"] += 1
    if rec["count"] >= MAX_FAILS:
        rec["lock_until"] = now + LOCK_SECONDS
        rec["count"] = 0
        rec["first"] = now
    FAILS[key] = rec


def set_session_cookie(resp, token):
    resp.set_cookie("sid", token, httponly=True, samesite="Lax", secure=COOKIE_SECURE, path="/")
    return resp


def valid_password(pw):
    return isinstance(pw, str) and len(pw) >= MIN_PASSWORD_LEN and len(pw) <= 100


# --------------------------------------------------------------------------- #
# Auth API
# --------------------------------------------------------------------------- #
@app.post("/api/login")
def api_login():
    data = body()
    username = str(data.get("username", "")).strip().lower()
    password = data.get("password", "")
    if not username or not isinstance(password, str) or not password:
        return err("กรุณากรอกชื่อผู้ใช้และรหัสผ่าน")
    key = (request.remote_addr, username)
    wait = locked_seconds(key)
    if wait:
        return err(f"ลองผิดหลายครั้งเกินไป กรุณารอ {wait} วินาที", 429)

    con = db()
    user = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        record_fail(key)
        return err("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", 401)
    if not user["active"]:
        return err("บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อผู้ดูแลระบบ", 403)
    FAILS.pop(key, None)

    now = time.time()
    token = secrets.token_urlsafe(32)
    con.execute("BEGIN IMMEDIATE")
    try:
        # ลบ session เก่าที่หมดอายุ (ไม่มี heartbeat) ของผู้ใช้นี้
        con.execute("DELETE FROM sessions WHERE user_id = ? AND last_seen < ?",
                    (user["id"], now - SESSION_TIMEOUT))
        active = con.execute("SELECT 1 FROM sessions WHERE user_id = ?", (user["id"],)).fetchone()
        if active:
            con.execute("ROLLBACK")
            return err("บัญชีนี้กำลังถูกใช้งานอยู่บนอุปกรณ์อื่น ไม่สามารถล็อกอินซ้อนได้ "
                       "(ให้ออกจากระบบที่เครื่องเดิมก่อน หรือรอสักครู่หากปิดหน้าเว็บไปแล้ว)", 409)
        con.execute(
            "INSERT INTO sessions (token, user_id, created_at, last_seen, ip) VALUES (?,?,?,?,?)",
            (token, user["id"], now, now, request.remote_addr),
        )
        con.execute("COMMIT")
    except sqlite3.IntegrityError:
        con.execute("ROLLBACK")
        return err("บัญชีนี้กำลังถูกใช้งานอยู่บนอุปกรณ์อื่น ไม่สามารถล็อกอินซ้อนได้", 409)
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    resp = jsonify({"user": user_dict(user)})
    return set_session_cookie(resp, token)


@app.post("/api/logout")
def api_logout():
    token = request.cookies.get("sid")
    if token:
        db().execute("DELETE FROM sessions WHERE token = ?", (token,))
    resp = jsonify({"ok": True})
    resp.delete_cookie("sid", path="/")
    return resp


@app.get("/api/me")
@login_required()
def api_me():
    return jsonify({"user": user_dict(g.user), "config": {
        "per_subject": PER_SUBJECT,
        "pass_percent": PASS_PERCENT,
        "subjects": [{"id": s["id"], "name": s["name"]} for s in sorted(SUBJECTS.values(), key=lambda x: x["id"])],
    }})


@app.post("/api/heartbeat")
@login_required()
def api_heartbeat():
    return jsonify({"ok": True})


@app.post("/api/change-password")
@login_required()
def api_change_password():
    data = body()
    old, new = data.get("old_password", ""), data.get("new_password", "")
    if not check_password_hash(g.user["password_hash"], old if isinstance(old, str) else ""):
        return err("รหัสผ่านเดิมไม่ถูกต้อง", 400)
    if not valid_password(new):
        return err(f"รหัสผ่านใหม่ต้องมีอย่างน้อย {MIN_PASSWORD_LEN} ตัวอักษร")
    db().execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                 (generate_password_hash(new, method=PW_METHOD), g.user["id"]))
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# Exam API
# --------------------------------------------------------------------------- #
def exam_row(exam_id):
    return db().execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()


def build_exam(user_id):
    con = db()
    picks = []
    for sid in sorted(SUBJECTS):
        ids = SUBJECTS[sid]["ids"]
        chosen = random.sample(ids, min(PER_SUBJECT, len(ids)))
        picks.extend((sid, qid) for qid in chosen)
    now = time.time()
    con.execute("BEGIN IMMEDIATE")
    try:
        # กันกดเริ่มซ้อน: ตรวจอีกครั้งในธุรกรรม
        existing = con.execute(
            "SELECT id FROM exams WHERE user_id=? AND status='in_progress'", (user_id,)).fetchone()
        if existing:
            con.execute("ROLLBACK")
            return existing["id"]
        cur = con.execute("INSERT INTO exams (user_id, status, started_at, total) VALUES (?, 'in_progress', ?, ?)",
                          (user_id, now, len(picks)))
        exam_id = cur.lastrowid
        rows = []
        for pos, (sid, qid) in enumerate(picks, start=1):
            n = len(QUESTIONS[qid]["c"])
            perm = random.sample(range(n), n)
            rows.append((exam_id, pos, qid, sid, json.dumps(perm)))
        con.executemany("INSERT INTO exam_items (exam_id, pos, q_id, subject_id, perm) VALUES (?,?,?,?,?)", rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return exam_id


def exam_payload(exam):
    rows = db().execute("SELECT * FROM exam_items WHERE exam_id=? ORDER BY pos", (exam["id"],)).fetchall()
    items = []
    for r in rows:
        q = QUESTIONS[r["q_id"]]
        perm = json.loads(r["perm"])
        items.append({
            "pos": r["pos"],
            "subject_id": r["subject_id"],
            "subject": SUBJECTS[r["subject_id"]]["name"],
            "q": q["q"],
            "choices": [q["c"][i] for i in perm],  # ไม่ส่งเฉลยไปที่เบราว์เซอร์
            "chosen": r["chosen"],
            "flagged": bool(r["flagged"]),
        })
    return {"id": exam["id"], "started_at": exam["started_at"], "total": exam["total"], "items": items}


@app.post("/api/exam/start")
@login_required()
def api_exam_start():
    if not SUBJECTS:
        return err("ยังไม่มีคลังข้อสอบ", 500)
    open_exam = db().execute(
        "SELECT * FROM exams WHERE user_id=? AND status='in_progress'", (g.user["id"],)).fetchone()
    if open_exam is None:
        exam_id = build_exam(g.user["id"])
        open_exam = exam_row(exam_id)
    return jsonify({"exam": exam_payload(open_exam)})


@app.get("/api/exam/current")
@login_required()
def api_exam_current():
    open_exam = db().execute(
        "SELECT * FROM exams WHERE user_id=? AND status='in_progress'", (g.user["id"],)).fetchone()
    if open_exam is None:
        return jsonify({"exam": None})
    return jsonify({"exam": exam_payload(open_exam)})


def own_open_exam(exam_id):
    exam = exam_row(exam_id)
    if exam is None or exam["user_id"] != g.user["id"]:
        return None, err("ไม่พบข้อสอบ", 404)
    if exam["status"] != "in_progress":
        return None, err("ข้อสอบนี้ส่งแล้ว", 409)
    return exam, None


@app.post("/api/exam/answer")
@login_required()
def api_exam_answer():
    data = body()
    exam, e = own_open_exam(data.get("exam_id"))
    if e:
        return e
    pos = data.get("pos")
    chosen = data.get("chosen")
    flagged = data.get("flagged")
    con = db()
    item = con.execute("SELECT perm FROM exam_items WHERE exam_id=? AND pos=?", (exam["id"], pos)).fetchone()
    if item is None:
        return err("ไม่พบข้อที่ระบุ", 404)
    n = len(json.loads(item["perm"]))
    if "chosen" in data:
        if chosen is not None and (not isinstance(chosen, int) or isinstance(chosen, bool) or not 0 <= chosen < n):
            return err("ตัวเลือกไม่ถูกต้อง")
        con.execute("UPDATE exam_items SET chosen=? WHERE exam_id=? AND pos=?", (chosen, exam["id"], pos))
    if flagged is not None:
        con.execute("UPDATE exam_items SET flagged=? WHERE exam_id=? AND pos=?",
                    (1 if flagged else 0, exam["id"], pos))
    return jsonify({"ok": True})


@app.post("/api/exam/submit")
@login_required()
def api_exam_submit():
    exam, e = own_open_exam(body().get("exam_id"))
    if e:
        return e
    con = db()
    rows = con.execute("SELECT * FROM exam_items WHERE exam_id=?", (exam["id"],)).fetchall()
    per_subject = {}
    score = 0
    for r in rows:
        q = QUESTIONS[r["q_id"]]
        perm = json.loads(r["perm"])
        ok = r["chosen"] is not None and perm[r["chosen"]] == q["a"]
        st = per_subject.setdefault(r["subject_id"], [0, 0])
        st[1] += 1
        if ok:
            st[0] += 1
            score += 1
    total = len(rows)
    percent = round(score * 100.0 / total, 2) if total else 0.0
    passed = 1 if percent >= PASS_PERCENT else 0
    con.execute("BEGIN IMMEDIATE")
    try:
        fresh = con.execute("SELECT status FROM exams WHERE id=?", (exam["id"],)).fetchone()
        if fresh["status"] != "in_progress":
            con.execute("ROLLBACK")
            return err("ข้อสอบนี้ส่งแล้ว", 409)
        con.execute("UPDATE exams SET status='submitted', submitted_at=?, score=?, percent=?, passed=? WHERE id=?",
                    (time.time(), score, percent, passed, exam["id"]))
        con.executemany("INSERT INTO exam_subject_scores (exam_id, subject_id, correct, total) VALUES (?,?,?,?)",
                        [(exam["id"], sid, c, t) for sid, (c, t) in per_subject.items()])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return jsonify({"ok": True, "exam_id": exam["id"]})


@app.post("/api/exam/abandon")
@login_required()
def api_exam_abandon():
    exam, e = own_open_exam(body().get("exam_id"))
    if e:
        return e
    db().execute("DELETE FROM exams WHERE id=?", (exam["id"],))
    return jsonify({"ok": True})


def exam_summary(exam):
    subj = db().execute("SELECT * FROM exam_subject_scores WHERE exam_id=? ORDER BY subject_id",
                        (exam["id"],)).fetchall()
    return {
        "id": exam["id"],
        "status": exam["status"],
        "started_at": exam["started_at"],
        "submitted_at": exam["submitted_at"],
        "score": exam["score"],
        "total": exam["total"],
        "percent": exam["percent"],
        "passed": None if exam["passed"] is None else bool(exam["passed"]),
        "pass_percent": PASS_PERCENT,
        "subjects": [{
            "id": s["subject_id"],
            "name": SUBJECTS[s["subject_id"]]["name"] if s["subject_id"] in SUBJECTS else str(s["subject_id"]),
            "correct": s["correct"],
            "total": s["total"],
            "percent": round(s["correct"] * 100.0 / s["total"], 2) if s["total"] else 0,
        } for s in subj],
    }


@app.get("/api/exams")
@login_required()
def api_exams():
    rows = db().execute("SELECT * FROM exams WHERE user_id=? ORDER BY started_at DESC", (g.user["id"],)).fetchall()
    return jsonify({"exams": [{k: v for k, v in exam_summary(r).items() if k != "subjects"} for r in rows]})


@app.get("/api/exams/<int:exam_id>")
@login_required()
def api_exam_detail(exam_id):
    exam = exam_row(exam_id)
    is_admin = g.user["role"] == "admin"
    if exam is None or (exam["user_id"] != g.user["id"] and not is_admin):
        return err("ไม่พบข้อสอบ", 404)
    owner = db().execute("SELECT username, display_name FROM users WHERE id=?", (exam["user_id"],)).fetchone()
    result = exam_summary(exam)
    result["owner"] = {"username": owner["username"], "display_name": owner["display_name"] or owner["username"]}
    rows = db().execute("SELECT * FROM exam_items WHERE exam_id=? ORDER BY pos", (exam_id,)).fetchall()
    if exam["status"] != "submitted":
        if not is_admin or exam["user_id"] == g.user["id"]:
            return err("ต้องส่งข้อสอบก่อนจึงจะดูเฉลยได้", 403)
        # แอดมินดูความคืบหน้าของข้อสอบที่ยังไม่ส่ง (ไม่เปิดเผยเฉลย)
        result["progress"] = {"answered": sum(1 for r in rows if r["chosen"] is not None), "total": len(rows)}
        result["items"] = []
        return jsonify({"result": result})
    items = []
    for r in rows:
        q = QUESTIONS.get(r["q_id"])
        if q is None:
            continue
        perm = json.loads(r["perm"])
        correct_display = perm.index(q["a"])
        items.append({
            "pos": r["pos"],
            "subject_id": r["subject_id"],
            "subject": SUBJECTS[r["subject_id"]]["name"],
            "q": q["q"],
            "choices": [q["c"][i] for i in perm],
            "chosen": r["chosen"],
            "correct": correct_display,
            "is_correct": r["chosen"] == correct_display,
            "explanation": q["e"],
        })
    result["items"] = items
    return jsonify({"result": result})


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
@app.get("/api/admin/users")
@login_required(admin=True)
def admin_users():
    now = time.time()
    rows = db().execute("""
        SELECT u.*,
               (SELECT COUNT(*) FROM exams e WHERE e.user_id=u.id AND e.status='submitted') AS exams_done,
               (SELECT MAX(e.percent) FROM exams e WHERE e.user_id=u.id AND e.status='submitted') AS best_percent,
               (SELECT s.last_seen FROM sessions s WHERE s.user_id=u.id) AS last_seen
        FROM users u ORDER BY u.id""").fetchall()
    users = []
    for r in rows:
        users.append({
            "id": r["id"], "username": r["username"], "display_name": r["display_name"],
            "role": r["role"], "active": bool(r["active"]), "created_at": r["created_at"],
            "exams_done": r["exams_done"], "best_percent": r["best_percent"],
            "online": r["last_seen"] is not None and now - r["last_seen"] <= SESSION_TIMEOUT,
        })
    return jsonify({"users": users})


@app.post("/api/admin/users")
@login_required(admin=True)
def admin_create_user():
    data = body()
    username = str(data.get("username", "")).strip().lower()
    display_name = str(data.get("display_name", "")).strip()[:100]
    password = data.get("password", "")
    role = data.get("role", "user")
    if not USERNAME_RE.match(username):
        return err("ชื่อผู้ใช้ต้องเป็นอักษรอังกฤษ/ตัวเลข/._- ยาว 3-30 ตัวอักษร")
    if not valid_password(password):
        return err(f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD_LEN} ตัวอักษร")
    if role not in ("admin", "user"):
        return err("บทบาทไม่ถูกต้อง")
    try:
        cur = db().execute(
            "INSERT INTO users (username, display_name, password_hash, role, active, created_at)"
            " VALUES (?,?,?,?,1,?)",
            (username, display_name, generate_password_hash(password, method=PW_METHOD), role, time.time()))
    except sqlite3.IntegrityError:
        return err("ชื่อผู้ใช้นี้มีอยู่แล้ว", 409)
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.patch("/api/admin/users/<int:uid>")
@login_required(admin=True)
def admin_update_user(uid):
    data = body()
    con = db()
    user = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user is None:
        return err("ไม่พบผู้ใช้", 404)
    if uid == g.user["id"] and (data.get("active") is False or data.get("role") == "user"):
        return err("ไม่สามารถระงับ/ลดสิทธิ์บัญชีของตัวเองได้")
    sets, params = [], []
    if "display_name" in data:
        sets.append("display_name=?")
        params.append(str(data["display_name"]).strip()[:100])
    if "role" in data:
        if data["role"] not in ("admin", "user"):
            return err("บทบาทไม่ถูกต้อง")
        sets.append("role=?")
        params.append(data["role"])
    if "active" in data:
        sets.append("active=?")
        params.append(1 if data["active"] else 0)
    if data.get("password"):
        if not valid_password(data["password"]):
            return err(f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD_LEN} ตัวอักษร")
        sets.append("password_hash=?")
        params.append(generate_password_hash(data["password"], method=PW_METHOD))
        sets.append("must_change_password=0")
    if sets:
        params.append(uid)
        con.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params)
    if data.get("active") is False or data.get("password"):
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    return jsonify({"ok": True})


@app.post("/api/admin/users/<int:uid>/force-logout")
@login_required(admin=True)
def admin_force_logout(uid):
    db().execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    return jsonify({"ok": True})


@app.get("/api/admin/exams")
@login_required(admin=True)
def admin_exams():
    uid = request.args.get("user_id", type=int)
    sql = """SELECT e.*, u.username, u.display_name,
                    (SELECT COUNT(*) FROM exam_items i WHERE i.exam_id=e.id AND i.chosen IS NOT NULL) AS answered
             FROM exams e JOIN users u ON u.id=e.user_id"""
    params = []
    if uid:
        sql += " WHERE e.user_id=?"
        params.append(uid)
    sql += " ORDER BY e.started_at DESC LIMIT 1000"
    rows = db().execute(sql, params).fetchall()
    return jsonify({"exams": [{
        "id": r["id"], "user_id": r["user_id"], "username": r["username"],
        "display_name": r["display_name"] or r["username"], "status": r["status"],
        "started_at": r["started_at"], "submitted_at": r["submitted_at"],
        "score": r["score"], "total": r["total"], "percent": r["percent"],
        "passed": None if r["passed"] is None else bool(r["passed"]), "answered": r["answered"],
    } for r in rows]})


@app.delete("/api/admin/exams/<int:exam_id>")
@login_required(admin=True)
def admin_delete_exam(exam_id):
    cur = db().execute("DELETE FROM exams WHERE id=?", (exam_id,))
    if cur.rowcount == 0:
        return err("ไม่พบข้อสอบ", 404)
    return jsonify({"ok": True})


@app.get("/api/admin/stats")
@login_required(admin=True)
def admin_stats():
    con = db()
    now = time.time()
    users = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    online = con.execute("SELECT COUNT(*) n FROM sessions WHERE last_seen >= ?", (now - SESSION_TIMEOUT,)).fetchone()["n"]
    done = con.execute("SELECT COUNT(*) n, AVG(percent) a, SUM(passed) p FROM exams WHERE status='submitted'").fetchone()
    inprog = con.execute("SELECT COUNT(*) n FROM exams WHERE status='in_progress'").fetchone()["n"]
    subj = con.execute("""SELECT subject_id, SUM(correct) c, SUM(total) t FROM exam_subject_scores
                          GROUP BY subject_id ORDER BY subject_id""").fetchall()
    return jsonify({
        "users": users, "online": online, "exams_submitted": done["n"], "exams_in_progress": inprog,
        "avg_percent": round(done["a"], 2) if done["a"] is not None else None,
        "pass_count": done["p"] or 0,
        "subjects": [{"id": s["subject_id"], "name": SUBJECTS.get(s["subject_id"], {}).get("name", ""),
                      "percent": round(s["c"] * 100.0 / s["t"], 2) if s["t"] else 0} for s in subj],
    })


def csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@app.get("/api/admin/exams.csv")
@login_required(admin=True)
def admin_exams_csv():
    con = db()
    rows = con.execute("""SELECT e.*, u.username, u.display_name FROM exams e
                          JOIN users u ON u.id=e.user_id WHERE e.status='submitted'
                          ORDER BY e.submitted_at DESC""").fetchall()
    scores = {}
    for s in con.execute("SELECT * FROM exam_subject_scores"):
        scores.setdefault(s["exam_id"], {})[s["subject_id"]] = s["correct"]
    sids = sorted(SUBJECTS)
    out = io.StringIO()
    w = csv.writer(out)
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else ""
    w.writerow(["รหัสสอบ", "ชื่อผู้ใช้", "ชื่อ-สกุล", "เริ่มสอบ", "ส่งข้อสอบ", "คะแนน", "เต็ม", "ร้อยละ", "ผล"]
               + [SUBJECTS[s]["name"] for s in sids])
    for r in rows:
        w.writerow([r["id"], csv_safe(r["username"]), csv_safe(r["display_name"]), fmt(r["started_at"]),
                    fmt(r["submitted_at"]), r["score"], r["total"], r["percent"],
                    "ผ่าน" if r["passed"] else "ไม่ผ่าน"] + [scores.get(r["id"], {}).get(s, "") for s in sids])
    data = "\ufeff" + out.getvalue()  # BOM ให้ Excel อ่านภาษาไทยถูกต้อง
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=exam_results.csv"})


# --------------------------------------------------------------------------- #
# Static / headers
# --------------------------------------------------------------------------- #
@app.after_request
def add_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/api/") or request.path.endswith(".html"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return err("ไม่พบหน้าที่ร้องขอ", 404)
    return redirect("/")


@app.errorhandler(500)
def server_error(_e):
    return err("เกิดข้อผิดพลาดภายในระบบ", 500)


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "login.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(PUBLIC_DIR, path)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "questions": len(QUESTIONS), "subjects": len(SUBJECTS)})


load_questions()
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False, threaded=True)
