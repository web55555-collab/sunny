"""
위탁관리업체 점검 관리 시스템 - Flask API 서버
실행: python app.py
접속: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3, os, csv, io
from datetime import datetime

app = Flask(__name__, static_folder="static")
CORS(app)

DB = "inspection.db"

# ───────────────────────────────── DB 초기화
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            area TEXT,
            contact TEXT,
            phone TEXT,
            cycle TEXT,
            day TEXT,
            type TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            vendor TEXT,
            area TEXT,
            inspector TEXT,
            items TEXT,
            result TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS specials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            vendor TEXT,
            type TEXT,
            content TEXT,
            status TEXT DEFAULT '미완료',
            next_date TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        """)

# ───────────────────────────────── 정적 파일 (프론트엔드)
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ───────────────────────────────── 업체 API
@app.route("/api/vendors", methods=["GET"])
def get_vendors():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/vendors", methods=["POST"])
def add_vendor():
    d = request.json
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO vendors (name,area,contact,phone,cycle,day,type) VALUES (?,?,?,?,?,?,?)",
                (d["name"], d.get("area",""), d.get("contact",""),
                 d.get("phone",""), d.get("cycle","주 1회"),
                 d.get("day","월"), d.get("type","기타"))
            )
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "이미 등록된 업체명입니다."}), 400

@app.route("/api/vendors/<int:vid>", methods=["DELETE"])
def del_vendor(vid):
    with get_db() as conn:
        conn.execute("DELETE FROM vendors WHERE id=?", (vid,))
    return jsonify({"ok": True})

# ───────────────────────────────── 점검 기록 API
@app.route("/api/records", methods=["GET"])
def get_records():
    vendor = request.args.get("vendor","")
    result = request.args.get("result","")
    month  = request.args.get("month","")
    date   = request.args.get("date","")
    query  = "SELECT * FROM records WHERE 1=1"
    params = []
    if vendor: query += " AND vendor=?";  params.append(vendor)
    if result: query += " AND result=?";  params.append(result)
    if month:  query += " AND date LIKE ?"; params.append(month+"%")
    if date:   query += " AND date=?";    params.append(date)
    query += " ORDER BY date DESC, id DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/records", methods=["POST"])
def add_record():
    d = request.json
    if not d.get("date"):
        return jsonify({"ok": False, "error": "날짜를 입력하세요."}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT INTO records (date,vendor,area,inspector,items,result,note) VALUES (?,?,?,?,?,?,?)",
            (d["date"], d.get("vendor",""), d.get("area",""),
             d.get("inspector",""), d.get("items",""),
             d.get("result","정상"), d.get("note",""))
        )
    return jsonify({"ok": True})

@app.route("/api/records/<int:rid>", methods=["DELETE"])
def del_record(rid):
    with get_db() as conn:
        conn.execute("DELETE FROM records WHERE id=?", (rid,))
    return jsonify({"ok": True})

# ───────────────────────────────── 특별 점검 API
@app.route("/api/specials", methods=["GET"])
def get_specials():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM specials ORDER BY date DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/specials", methods=["POST"])
def add_special():
    d = request.json
    if not d.get("date") or not d.get("title"):
        return jsonify({"ok": False, "error": "날짜와 제목을 입력하세요."}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT INTO specials (date,title,vendor,type,content,status,next_date) VALUES (?,?,?,?,?,?,?)",
            (d["date"], d["title"], d.get("vendor",""), d.get("type","기타"),
             d.get("content",""), d.get("status","미완료"), d.get("next_date",""))
        )
    return jsonify({"ok": True})

@app.route("/api/specials/<int:sid>", methods=["PATCH"])
def update_special(sid):
    d = request.json
    with get_db() as conn:
        conn.execute("UPDATE specials SET status=? WHERE id=?", (d["status"], sid))
    return jsonify({"ok": True})

@app.route("/api/specials/<int:sid>", methods=["DELETE"])
def del_special(sid):
    with get_db() as conn:
        conn.execute("DELETE FROM specials WHERE id=?", (sid,))
    return jsonify({"ok": True})

# ───────────────────────────────── 요약 통계 API
@app.route("/api/summary", methods=["GET"])
def get_summary():
    month = datetime.now().strftime("%Y-%m")
    with get_db() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM records WHERE date LIKE ?", (month+"%",)).fetchone()[0]
        normal  = conn.execute("SELECT COUNT(*) FROM records WHERE date LIKE ? AND result='정상'", (month+"%",)).fetchone()[0]
        warn    = conn.execute("SELECT COUNT(*) FROM records WHERE date LIKE ? AND result IN ('주의','불량')", (month+"%",)).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM specials WHERE status != '완료'").fetchone()[0]
    return jsonify({"total": total, "normal": normal, "warn_bad": warn, "pending_special": pending})

# ───────────────────────────────── CSV 내보내기
@app.route("/api/export/csv", methods=["GET"])
def export_csv():
    with get_db() as conn:
        rows = conn.execute("SELECT date,vendor,area,inspector,items,result,note FROM records ORDER BY date DESC").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["날짜","업체","구역","점검자","점검항목","결과","특이사항"])
    for r in rows:
        writer.writerow(list(r))
    from flask import Response
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=inspection_records.csv"}
    )

if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("  위탁관리업체 점검 관리 시스템 서버 시작")
    print("  브라우저에서 열기: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5000)
