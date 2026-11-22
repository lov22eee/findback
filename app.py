
import sqlite3
import secrets
from pathlib import Path
from datetime import date
from flask import Flask, request, render_template_string

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "data" / "findback.db"


# 데이터베이스 테이블 준비
def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                item_name TEXT NOT NULL,
                place TEXT NOT NULL,
                event_date TEXT NOT NULL,
                description TEXT,
                manage_code TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS return_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                requester_name TEXT NOT NULL,
                verification_note TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)


@app.route("/", methods=["GET", "POST"])
def home():
    message = ""
    message_type = "success"
    issued_code = ""
    results = []
    requests_list = []
    managed_item = None
    searched = False
    keyword = ""
    search_type = "all"

    action = request.form.get("action", "")

    # 1. 분실물 및 습득물 등록
    if request.method == "POST" and action == "register":
        item_type = request.form.get("item_type", "")
        item_name = request.form.get("item_name", "").strip()
        place = request.form.get("place", "").strip()
        event_date = request.form.get("event_date", "")
        description = request.form.get("description", "").strip()

        if (
            item_type not in ("lost", "found")
            or not item_name
            or not place
            or not event_date
        ):
            message = "필수 정보를 모두 입력해주세요."
            message_type = "error"
        else:
            try:
                parsed_date = date.fromisoformat(event_date)

                if parsed_date > date.today():
                    message = "미래 날짜는 등록할 수 없습니다."
                    message_type = "error"
                else:
                    # 습득물 등록 시 관리 코드 발급
                    manage_code = (
                        secrets.token_urlsafe(16)
                        if item_type == "found" else None
                    )

                    with sqlite3.connect(DB_PATH) as conn:
                        cursor = conn.execute("""
                            INSERT INTO items
                            (item_type, item_name, place,
                             event_date, description, manage_code)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            item_type, item_name, place,
                            event_date, description, manage_code
                        ))
                        item_id = cursor.lastrowid

                    message = f"등록 완료! 게시글 번호: {item_id}"
                    issued_code = manage_code or ""

            except ValueError:
                message = "올바른 날짜를 입력해주세요."
                message_type = "error"

    # 2. 반환 요청 접수
    if request.method == "POST" and action == "return_request":
        item_id = request.form.get("item_id", "").strip()
        requester_name = request.form.get("requester_name", "").strip()
        verification_note = request.form.get(
            "verification_note", ""
        ).strip()

        keyword = request.form.get("q", "").strip()
        search_type = request.form.get("type", "all")

        if not item_id.isdigit():
            message = "올바른 게시글 번호가 아닙니다."
            message_type = "error"
        elif not requester_name or not verification_note:
            message = "요청자 이름과 물품 특징을 모두 입력해주세요."
            message_type = "error"
        else:
            with sqlite3.connect(DB_PATH) as conn:
                item = conn.execute(
                    "SELECT item_type FROM items WHERE id = ?",
                    (int(item_id),)
                ).fetchone()

                if item is None:
                    message = "존재하지 않는 게시글입니다."
                    message_type = "error"
                elif item[0] != "found":
                    message = "습득물에만 반환 요청할 수 있습니다."
                    message_type = "error"
                else:
                    cursor = conn.execute("""
                        INSERT INTO return_requests
                        (item_id, requester_name, verification_note)
                        VALUES (?, ?, ?)
                    """, (
                        int(item_id),
                        requester_name,
                        verification_note
                    ))
                    message = (
                        f"반환 요청이 접수되었습니다. "
                        f"요청 번호: {cursor.lastrowid}"
                    )

    # 3. 관리 코드로 반환 요청 목록 확인
    if request.method == "POST" and action == "manage":
        item_id = request.form.get("manage_item_id", "").strip()
        input_code = request.form.get("manage_code", "").strip()

        if not item_id.isdigit() or not input_code:
            message = "게시글 번호와 관리 코드를 입력해주세요."
            message_type = "error"
        else:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row

                item = conn.execute("""
                    SELECT id, item_name, manage_code
                    FROM items
                    WHERE id = ? AND item_type = 'found'
                """, (int(item_id),)).fetchone()

                if (
                    item is None
                    or not item["manage_code"]
                    or not secrets.compare_digest(
                        input_code, item["manage_code"]
                    )
                ):
                    message = "게시글 번호 또는 관리 코드가 올바르지 않습니다."
                    message_type = "error"
                else:
                    managed_item = dict(item)

                    rows = conn.execute("""
                        SELECT id, requester_name,
                               verification_note, status
                        FROM return_requests
                        WHERE item_id = ?
                        ORDER BY id DESC
                    """, (int(item_id),)).fetchall()

                    requests_list = [dict(row) for row in rows]
                    message = "반환 요청 목록 조회 성공"

    # 4. 물품 검색
    if request.method == "GET" and "q" in request.args:
        keyword = request.args.get("q", "").strip()
        search_type = request.args.get("type", "all")

        if not keyword:
            message = "검색어를 입력해주세요."
            message_type = "error"

    if keyword:
        searched = True
        search_word = f"%{keyword}%"

        sql = """
            SELECT id, item_type, item_name,
                   place, event_date, description
            FROM items
            WHERE (
                item_name LIKE ?
                OR place LIKE ?
                OR description LIKE ?
            )
        """
        params = [search_word, search_word, search_word]

        if search_type in ("lost", "found"):
            sql += " AND item_type = ?"
            params.append(search_type)

        sql += " ORDER BY id DESC"

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            results = [dict(row) for row in rows]

    # 웹페이지 디자인 및 출력
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>FindBack | 분실물 찾기</title>

        <style>
            :root { --ink:#173b3a; --teal:#157a6e; --muted:#73817d; --line:#dfe8e2; }
            * { box-sizing:border-box; }
            html { scroll-behavior:smooth; }
            body { margin:0; background:#f5f7f2; color:var(--ink); font-family:"Malgun Gothic",Arial,sans-serif; line-height:1.6; }
            a { color:inherit; text-decoration:none; }
            .topbar { background:#fff; border-bottom:1px solid var(--line); }
            .nav-inner { max-width:1140px; margin:auto; min-height:72px; padding:0 28px; display:flex; align-items:center; justify-content:space-between; gap:20px; }
            .brand { display:flex; align-items:center; gap:10px; font-size:23px; font-weight:800; letter-spacing:-1px; }
            .brand-mark { width:33px; height:33px; border-radius:11px; background:var(--teal); display:grid; place-items:center; color:white; font-size:22px; }
            nav { display:flex; gap:26px; font-size:13px; color:#61736c; font-weight:700; }
            nav a:hover { color:var(--teal); }
            header { max-width:1140px; margin:auto; padding:34px 28px 30px; display:flex; justify-content:space-between; align-items:center; gap:32px; }
            .eyebrow { color:var(--teal); letter-spacing:2px; font-size:10px; font-weight:800; margin:0 0 10px; }
            header h1 { font-size:35px; line-height:1.35; letter-spacing:-1.8px; margin:0 0 10px; font-weight:800; }
            header h1 span { color:var(--teal); }
            header p { color:#708078; margin:0; font-size:13px; }
            .hero-note { display:flex; align-items:center; gap:17px; padding:19px 23px; background:#e9f0e5; border:1px solid #dce7d5; border-radius:18px; transform:rotate(-2deg); min-width:245px; }
            .hero-icon { width:53px; height:53px; color:var(--teal); background:#fff; border-radius:16px; display:grid; place-items:center; }
            .hero-note strong { display:block; font-size:13px; margin-bottom:4px; }
            .hero-note small { color:#7c8874; font-size:11px; }
            .container { max-width:1140px; margin:28px auto 0; padding:0 28px; }
            .workspace { display:grid; grid-template-columns:1.05fr .95fr; gap:20px; align-items:start; }
            .panel { background:#fff; border:1px solid var(--line); border-radius:18px; padding:24px; box-shadow:0 4px 20px #193e2d04; scroll-margin-top:20px; min-width:0; }
            .register-panel { grid-column:1; grid-row:1 / span 2; border-top:3px solid var(--teal); }
            .search-panel,.manage-panel { grid-column:2; }
            h2 { margin:0 0 6px; font-size:18px; letter-spacing:-.7px; display:flex; gap:9px; align-items:center; }
            h3 { font-size:14px; margin:0 0 10px; }
            .step { font-size:10px; letter-spacing:0; padding:3px 7px; border-radius:6px; color:var(--teal); background:#eaf3ee; font-weight:800; }
            .subtitle { color:var(--muted); font-size:11px; margin:0 0 21px; }
            .form-grid { display:grid; grid-template-columns:1fr 1fr; gap:15px; }
            .wide { grid-column:1 / -1; }
            label { display:block; font-size:11px; font-weight:700; color:#53675e; }
            input,select,textarea { display:block; width:100%; min-width:0; margin-top:7px; padding:10px 11px; border:1px solid #dce5de; border-radius:8px; background:#fbfcf9; color:var(--ink); font:inherit; font-size:12px; transition:border-color .15s,box-shadow .15s; }
            input,select { min-height:41px; }
            input::placeholder,textarea::placeholder { color:#9aa69e; }
            input:focus,select:focus,textarea:focus { outline:none; border-color:#409c86; box-shadow:0 0 0 3px #157a6e12; background:white; }
            textarea { min-height:96px; resize:vertical; }
            button { background:var(--teal); color:white; border:1px solid transparent; border-radius:8px; padding:11px 16px; font:inherit; font-size:12px; font-weight:700; cursor:pointer; transition:background .15s,transform .15s; }
            button:hover { background:#106359; }
            button:active { transform:translateY(1px); }
            button:focus-visible,a:focus-visible { outline:3px solid #edb76c; outline-offset:3px; }
            .register-panel button.wide { margin-top:3px; }
            .manage-panel button.wide { color:var(--teal); border-color:#c8ded3; background:#edf5ef; }
            .manage-panel button.wide:hover { background:#dfeee3; }
            .form-note { margin:14px 0 0; font-size:10px; color:#8a978e; display:flex; align-items:center; gap:6px; }
            .form-note::before { content:""; width:5px; height:5px; border-radius:50%; background:#91ac92; flex:none; }
            .notice { border:1px solid #c7e3cf; border-radius:10px; padding:14px 18px; margin-bottom:18px; background:#e9f5ec; color:#246246; overflow-wrap:anywhere; font-size:13px; }
            .notice.error { background:#fff2ea; border-color:#f2dac8; color:#a75532; }
            .manage-code { background:#edf4ef; border:1px solid #c8dfd0; border-radius:12px; padding:17px; margin-bottom:18px; overflow-wrap:anywhere; font-size:13px; }
            .manage-code p { margin:8px 0; }
            .search-bar { display:grid; grid-template-columns:minmax(0,1fr) 83px auto; gap:7px; align-items:end; }
            .search-bar input,.search-bar select { margin:0; }
            .search-bar button { padding:11px 12px; min-height:41px; }
            .search-hint { font-size:10px; color:#9aa69e; margin:13px 0 0; }
            .results { display:grid; grid-template-columns:1fr; gap:14px; margin-top:18px; }
            .item-card { border:1px solid #dfe8e0; border-radius:12px; padding:18px; min-width:0; background:#fcfdfb; }
            .tag { display:inline-block; padding:3px 8px; border-radius:5px; font-size:10px; font-weight:700; background:#eef0fa; color:#686eaf; margin-bottom:10px; }
            .tag.found { background:#e5f1e9; color:#357d57; }
            .item-card h3 { font-size:16px; overflow-wrap:anywhere; }
            .item-card p { margin:5px 0; font-size:11px; color:#718174; overflow-wrap:anywhere; }
            .request-box { border-top:1px dashed #dbe6dd; padding-top:15px; margin-top:16px; }
            .request-box input,.request-box textarea { margin-bottom:10px; }
            .request-entry { background:#f0f6ef; border:1px solid #dce8db; border-radius:10px; padding:15px; margin-top:12px; font-size:12px; overflow-wrap:anywhere; }
            .request-entry p { margin:5px 0; font-size:11px; color:#6c7f70; }
            footer { max-width:1084px; margin:26px auto 0; border-top:1px solid #e1e8df; padding:17px 0 22px; color:#8c9990; font-size:10px; display:flex; justify-content:space-between; gap:12px; }
            footer strong { color:#698074; letter-spacing:-.3px; }
            @media(max-width:760px) {
                .nav-inner { padding:0 20px; min-height:62px; } nav { gap:15px; font-size:11px; }
                header { padding:27px 20px 24px; } header h1 { font-size:29px; } .hero-note { display:none; }
                .container { padding:0 16px; } .workspace { grid-template-columns:1fr; gap:16px; }
                .register-panel,.search-panel,.manage-panel { grid-column:auto; grid-row:auto; }
                .panel { padding:20px; } footer { margin:24px 16px 0; }
            }
            @media(max-width:400px) { .form-grid { grid-template-columns:1fr; } .search-bar { grid-template-columns:minmax(0,1fr) 76px; } .search-bar button { grid-column:1/-1; } nav { gap:10px; } }
            @media(prefers-reduced-motion:reduce) { html { scroll-behavior:auto; } * { transition:none !important; } }
        </style>
    </head>

    <body>

        <div class="topbar">
            <div class="nav-inner">
                <a class="brand" href="/" aria-label="FindBack 홈"><span class="brand-mark" aria-hidden="true">↗</span>FindBack<span style="color:#71a98c">.</span></a>
            </div>
        </div>

        <main class="container">

            {% if message %}
                <div class="notice {{ 'error' if message_type == 'error' else '' }}">
                    <strong>{{ message }}</strong>
                </div>
            {% endif %}

            {% if issued_code %}
                <div class="manage-code">
                    <strong>게시글 관리 코드</strong>
                    <p><code>{{ issued_code }}</code></p>
                    <small>
                        반환 요청을 확인할 때 필요합니다.
                        지금 별도로 안전하게 보관하세요.
                    </small>
                </div>
            {% endif %}

            <div class="workspace">
            <section class="panel register-panel" id="register">
                <h2><span class="step">01</span> 분실물 · 습득물 등록</h2>
                <p class="subtitle">
                    잃어버렸거나 주운 물건의 정보를 등록하세요.
                </p>

                <form method="POST" class="form-grid">
                    <input type="hidden" name="action" value="register">

                    <label>
                        등록 유형
                        <select name="item_type">
                            <option value="lost">분실물 (잃어버림)</option>
                            <option value="found">습득물 (주운 물건)</option>
                        </select>
                    </label>

                    <label>
                        물품 이름
                        <input name="item_name" placeholder="예: 검은색 지갑">
                    </label>

                    <label>
                        분실 · 발견 장소
                        <input name="place" placeholder="예: 서울역">
                    </label>

                    <label>
                        날짜
                        <input type="date" name="event_date">
                    </label>

                    <label class="wide">
                        상세 특징
                        <textarea name="description"
                                  placeholder="물건의 색상, 모양 등"></textarea>
                    </label>

                    <button type="submit" class="wide">
                        물품 등록하기
                    </button>
                </form>
                <p class="form-note">습득물 등록 후 발급되는 관리 코드를 보관해 주세요.</p>
            </section>

            <section class="panel search-panel" id="search">
                <h2><span class="step">02</span> 물품 검색 · 반환 요청</h2>
                <p class="subtitle">
                    물품 이름, 장소 또는 특징으로 검색하세요.
                </p>

                <form method="GET" class="search-bar">
                    <input name="q" value="{{ keyword }}"
                           placeholder="예: 지갑, 우산, 서울역">

                    <select name="type">
                        <option value="all"
                            {% if search_type == "all" %}selected{% endif %}>
                            전체
                        </option>
                        <option value="lost"
                            {% if search_type == "lost" %}selected{% endif %}>
                            분실물
                        </option>
                        <option value="found"
                            {% if search_type == "found" %}selected{% endif %}>
                            습득물
                        </option>
                    </select>

                    <button type="submit">검색하기</button>
                </form>

                {% if not searched %}<p class="search-hint">이름이 기억나지 않아도 장소나 색상으로 찾아보세요.</p>{% endif %}
                {% if searched %}
                    <h3 style="margin-top:25px">
                        검색 결과 {{ results|length }}건
                    </h3>

                    {% if results %}
                        <div class="results">
                            {% for item in results %}
                                <div class="item-card">
                                    <span class="tag {{ item.item_type }}">
                                        {{ "분실물" if item.item_type == "lost"
                                           else "습득물" }}
                                    </span>

                                    <h3>{{ item.item_name }}</h3>
                                    <p>게시글 번호: {{ item.id }}</p>
                                    <p>장소: {{ item.place }}</p>
                                    <p>날짜: {{ item.event_date }}</p>
                                    <p>특징: {{ item.description }}</p>

                                    {% if item.item_type == "found" %}
                                        <div class="request-box">
                                            <h3>반환 요청</h3>

                                            <form method="POST">
                                                <input type="hidden"
                                                       name="action"
                                                       value="return_request">
                                                <input type="hidden"
                                                       name="item_id"
                                                       value="{{ item.id }}">
                                                <input type="hidden"
                                                       name="q"
                                                       value="{{ keyword }}">
                                                <input type="hidden"
                                                       name="type"
                                                       value="{{ search_type }}">

                                                <input name="requester_name"
                                                       placeholder="요청자 이름 또는 별명">

                                                <textarea name="verification_note"
                                                    placeholder="본인 물품임을 확인할 추가 특징"></textarea>

                                                <button type="submit">
                                                    반환 요청하기
                                                </button>
                                            </form>
                                        </div>
                                    {% endif %}
                                </div>
                            {% endfor %}
                        </div>
                    {% else %}
                        <p>검색 결과가 없습니다.</p>
                    {% endif %}
                {% endif %}
            </section>

            <section class="panel manage-panel" id="manage">
                <h2><span class="step">03</span> 반환 요청 관리</h2>
                <p class="subtitle">
                    습득물을 등록한 사람이 관리 코드로 요청을 확인합니다.
                </p>

                <form method="POST" class="form-grid">
                    <input type="hidden" name="action" value="manage">

                    <label>
                        게시글 번호
                        <input type="number" name="manage_item_id"
                               placeholder="게시글 번호">
                    </label>

                    <label>
                        게시글 관리 코드
                        <input type="password" name="manage_code"
                               placeholder="관리 코드">
                    </label>

                    <button type="submit" class="wide">
                        반환 요청 확인하기
                    </button>
                </form>

                {% if managed_item %}
                    <h3 style="margin-top:25px">
                        {{ managed_item.item_name }} - 반환 요청 목록
                    </h3>

                    {% if requests_list %}
                        {% for req in requests_list %}
                            <div class="request-entry">
                                <strong>요청 번호 {{ req.id }}</strong>
                                <p>요청자: {{ req.requester_name }}</p>
                                <p>추가 특징: {{ req.verification_note }}</p>
                                <p>상태: {{ req.status }}</p>
                            </div>
                        {% endfor %}
                    {% else %}
                        <p>접수된 반환 요청이 없습니다.</p>
                    {% endif %}
                {% endif %}
            </section>
            </div>
        </main>

        <footer>
            <strong>FindBack.</strong><span>다시 만나는 일상을 위해 · 분실물 찾기 서비스</span>
        </footer>
    </body>
    </html>
    """, message=message, message_type=message_type,
       issued_code=issued_code, results=results,
       searched=searched, keyword=keyword,
       search_type=search_type, managed_item=managed_item,
       requests_list=requests_list)


# 로컬 개발 서버
if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
