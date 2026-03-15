"""
위탁관리업체 점검 관리 시스템 - Flask API 서버
실행: python app.py
접속: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import sqlite3, os, csv, io, base64
from datetime import datetime

app = Flask(__name__, static_folder="static")
CORS(app)

# ───────────────────────────────── 기본 인증
@app.before_request
def basic_auth():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Basic '):
        credentials = base64.b64decode(auth[6:]).decode('utf-8')
        username, password = credentials.split(':', 1)
        if username == os.environ.get('AUTH_USER', 'admin') and \
           password == os.environ.get('AUTH_PASS', '1234'):
            return None
    return Response(
        'Login required', 401,
        {'WWW-Authenticate': 'Basic realm="Inspection System"'}
    )

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
            -- 수처리 관련 필드
            treatment_method TEXT,          -- 수처리공법
            facility_capacity TEXT,         -- 수처리시설용량 (㎥/일)
            construction_date TEXT,         -- 최초시공일(준공일)
            -- 처리수 배출기준 (mg/L)
            standard_bod TEXT,              -- BOD 기준
            standard_ss TEXT,               -- SS 기준
            standard_tn TEXT,               -- T-N 기준
            standard_tp TEXT,               -- T-P 기준
            standard_coliform TEXT,         -- 총대장균군수 기준 (CFU/mL)
            -- 최종처리수 배출구 방법
            discharge_method TEXT,          -- '자연배수로' 또는 '시·도 처리장'
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

    # 기존 DB에 컬럼이 없을 경우 마이그레이션
    new_columns = [
        ("treatment_method",  "TEXT"),
        ("facility_capacity", "TEXT"),
        ("construction_date", "TEXT"),
        ("standard_bod",      "TEXT"),
        ("standard_ss",       "TEXT"),
        ("standard_tn",       "TEXT"),
        ("standard_tp",       "TEXT"),
        ("standard_coliform", "TEXT"),
        ("discharge_method",  "TEXT"),
    ]
    with get_db() as conn:
        existing = [row[1] for row in conn.execute("PRAGMA table_info(vendors)").fetchall()]
        for col_name, col_type in new_columns:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE vendors ADD COLUMN {col_name} {col_type}")

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
                """INSERT INTO vendors
                   (name, area, contact, phone, cycle, day,
                    treatment_method, facility_capacity, construction_date,
                    standard_bod, standard_ss, standard_tn, standard_tp,
                    standard_coliform, discharge_method)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["name"],
                    d.get("area", ""),
                    d.get("contact", ""),
                    d.get("phone", ""),
                    d.get("cycle", "주 1회"),
                    d.get("day", "월"),
                    d.get("treatment_method", ""),
                    d.get("facility_capacity", ""),
                    d.get("construction_date", ""),
                    d.get("standard_bod", ""),
                    d.get("standard_ss", ""),
                    d.get("standard_tn", ""),
                    d.get("standard_tp", ""),
                    d.get("standard_coliform", ""),
                    d.get("discharge_method", "자연배수로"),
                )
            )
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "이미 등록된 업체명입니다."}), 400

@app.route("/api/vendors/<int:vid>", methods=["PUT"])
def update_vendor(vid):
    d = request.json
    with get_db() as conn:
        conn.execute(
            """UPDATE vendors SET
               area=?, contact=?, phone=?, cycle=?, day=?,
               treatment_method=?, facility_capacity=?, construction_date=?,
               standard_bod=?, standard_ss=?, standard_tn=?, standard_tp=?,
               standard_coliform=?, discharge_method=?
               WHERE id=?""",
            (
                d.get("area", ""),
                d.get("contact", ""),
                d.get("phone", ""),
                d.get("cycle", "주 1회"),
                d.get("day", "월"),
                d.get("treatment_method", ""),
                d.get("facility_capacity", ""),
                d.get("construction_date", ""),
                d.get("standard_bod", ""),
                d.get("standard_ss", ""),
                d.get("standard_tn", ""),
                d.get("standard_tp", ""),
                d.get("standard_coliform", ""),
                d.get("discharge_method", "자연배수로"),
                vid,
            )
        )
    return jsonify({"ok": True})

@app.route("/api/vendors/<int:vid>", methods=["DELETE"])
def del_vendor(vid):
    with get_db() as conn:
        conn.execute("DELETE FROM vendors WHERE id=?", (vid,))
    return jsonify({"ok": True})

# ───────────────────────────────── 점검 기록 API
@app.route("/api/records", methods=["GET"])
def get_records():
    vendor = request.args.get("vendor", "")
    result = request.args.get("result", "")
    month  = request.args.get("month", "")
    date   = request.args.get("date", "")
    query  = "SELECT * FROM records WHERE 1=1"
    params = []
    if vendor: query += " AND vendor=?";    params.append(vendor)
    if result: query += " AND result=?";    params.append(result)
    if month:  query += " AND date LIKE ?"; params.append(month + "%")
    if date:   query += " AND date=?";      params.append(date)
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
            (d["date"], d.get("vendor", ""), d.get("area", ""),
             d.get("inspector", ""), d.get("items", ""),
             d.get("result", "정상"), d.get("note", ""))
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
            (d["date"], d["title"], d.get("vendor", ""), d.get("type", "기타"),
             d.get("content", ""), d.get("status", "미완료"), d.get("next_date", ""))
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
        total   = conn.execute("SELECT COUNT(*) FROM records WHERE date LIKE ?", (month + "%",)).fetchone()[0]
        normal  = conn.execute("SELECT COUNT(*) FROM records WHERE date LIKE ? AND result='정상'", (month + "%",)).fetchone()[0]
        warn    = conn.execute("SELECT COUNT(*) FROM records WHERE date LIKE ? AND result IN ('주의','불량')", (month + "%",)).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM specials WHERE status != '완료'").fetchone()[0]
    return jsonify({"total": total, "normal": normal, "warn_bad": warn, "pending_special": pending})

# ───────────────────────────────── CSV 내보내기
@app.route("/api/export/csv", methods=["GET"])
def export_csv():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date,vendor,area,inspector,items,result,note FROM records ORDER BY date DESC"
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["날짜", "업체", "구역", "점검자", "점검항목", "결과", "특이사항"])
    for r in rows:
        writer.writerow(list(r))
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=inspection_records.csv"}
    )

# ───────────────────────────────── 업체 수처리 정보 CSV 내보내기
@app.route("/api/export/vendors_csv", methods=["GET"])
def export_vendors_csv():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT name, area, contact, phone, cycle, day,
                      treatment_method, facility_capacity, construction_date,
                      standard_bod, standard_ss, standard_tn, standard_tp,
                      standard_coliform, discharge_method
               FROM vendors ORDER BY name"""
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "업체명", "구역", "담당자", "연락처", "점검주기", "점검요일",
        "수처리공법", "시설용량(㎥/일)", "최초시공일(준공일)",
        "BOD기준(mg/L)", "SS기준(mg/L)", "T-N기준(mg/L)", "T-P기준(mg/L)",
        "총대장균군수기준(CFU/mL)", "최종배출방법"
    ])
    for r in rows:
        writer.writerow(list(r))
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=vendors_info.csv"}
    )

if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("  위탁관리업체 점검 관리 시스템 서버 시작")
    print("  브라우저에서 열기: http://localhost:5000")
    print("=" * 50)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
