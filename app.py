from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool
import os
import json
import secrets
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'goaldigger-change-this-in-production')

# ---------------------------------------------------------------------------
# SPORT CATALOGUE
# ---------------------------------------------------------------------------

SPORTS = [
    {"name": "Football",     "icon": "⚽"},
    {"name": "Basketball",   "icon": "🏀"},
    {"name": "Swimming",     "icon": "🏊"},
    {"name": "Tennis",       "icon": "🎾"},
    {"name": "Gymnastics",   "icon": "🤸"},
    {"name": "Athletics",    "icon": "🏃"},
    {"name": "Volleyball",   "icon": "🏐"},
    {"name": "Baseball",     "icon": "⚾"},
    {"name": "Cycling",      "icon": "🚴"},
    {"name": "Martial Arts", "icon": "🥋"},
    {"name": "Hockey",       "icon": "🏒"},
    {"name": "Rugby",        "icon": "🏉"},
    {"name": "Badminton",    "icon": "🏸"},
    {"name": "Golf",         "icon": "⛳"},
    {"name": "Skiing",       "icon": "⛷️"},
    {"name": "Dance",        "icon": "💃"},
    {"name": "Rowing",       "icon": "🚣"},
    {"name": "Climbing",     "icon": "🧗"},
    {"name": "Handball",     "icon": "🤾"},
    {"name": "Cricket",      "icon": "🏏"},
]

SPORT_ICONS = {s["name"]: s["icon"] for s in SPORTS}

SPORT_SKILLS = {
    "Football":     ["Passing", "Dribbling", "Shooting", "Heading", "Tackling", "Positioning", "Set pieces", "Goalkeeping"],
    "Basketball":   ["Dribbling", "Passing", "Shooting", "Defense", "Rebounding", "Footwork", "Pick and roll", "Free throws"],
    "Swimming":     ["Freestyle", "Backstroke", "Breaststroke", "Butterfly", "Turns", "Starts", "Breathing", "Endurance"],
    "Tennis":       ["Forehand", "Backhand", "Serve", "Volley", "Footwork", "Return", "Slice", "Topspin"],
    "Gymnastics":   ["Tumbling", "Balance beam", "Vault", "Bars", "Floor routine", "Flexibility", "Handstands", "Cartwheels"],
    "Athletics":    ["Sprinting", "Long distance", "Hurdles", "Long jump", "High jump", "Shot put", "Discus", "Relay"],
    "Volleyball":   ["Serving", "Setting", "Spiking", "Blocking", "Digging", "Positioning", "Communication", "Footwork"],
    "Baseball":     ["Batting", "Pitching", "Fielding", "Base running", "Catching", "Throwing", "Stance", "Bunting"],
    "Cycling":      ["Endurance", "Sprinting", "Climbing", "Descending", "Cornering", "Cadence", "Drafting", "Position"],
    "Martial Arts": ["Punching", "Kicking", "Blocking", "Kata", "Sparring", "Grappling", "Stance", "Balance"],
    "Hockey":       ["Skating", "Stickhandling", "Shooting", "Passing", "Checking", "Positioning", "Goaltending", "Face-offs"],
    "Rugby":        ["Tackling", "Passing", "Kicking", "Scrumming", "Lineout", "Running", "Defense", "Rucking"],
    "Badminton":    ["Serve", "Smash", "Drop shot", "Clear", "Footwork", "Net play", "Defense", "Positioning"],
    "Golf":         ["Driving", "Iron play", "Chipping", "Putting", "Bunker play", "Course management", "Stance", "Swing"],
    "Skiing":       ["Balance", "Carving", "Moguls", "Speed control", "Jumping", "Slalom", "Posture", "Edge control"],
    "Dance":        ["Technique", "Choreography", "Rhythm", "Flexibility", "Strength", "Expression", "Timing", "Partner work"],
    "Rowing":       ["Catch", "Drive", "Finish", "Recovery", "Balance", "Timing", "Endurance", "Technique"],
    "Climbing":     ["Footwork", "Grip", "Route reading", "Balance", "Overhang", "Slab", "Dynos", "Endurance"],
    "Handball":     ["Passing", "Shooting", "Dribbling", "Defense", "Goalkeeping", "Positioning", "Blocking", "Footwork"],
    "Cricket":      ["Batting", "Bowling", "Fielding", "Wicket-keeping", "Running between wickets", "Spin bowling", "Pace bowling", "Catching"],
}
DEFAULT_SKILLS = ["Technique", "Conditioning", "Tactics", "Coordination", "Endurance", "Speed", "Strength", "Teamwork"]

AVATAR_COLORS = ['#6366F1', '#EC4899', '#14B8A6', '#F59E0B', '#8B5CF6', '#06B6D4', '#84CC16', '#EF4444']

# ---------------------------------------------------------------------------
# DATABASE — connection pool + per-request connection via Flask g
# ---------------------------------------------------------------------------

_pool = None

def _db_url():
    url = os.environ.get('DATABASE_URL', '')
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return url.replace('postgres://', 'postgresql://', 1) if url.startswith('postgres://') else url

def get_pool():
    """Initialise the connection pool once and reuse it."""
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(1, 10, _db_url())
    return _pool

def get_connection():
    """Return a connection for the current request, reusing it if already open."""
    if 'db_conn' not in g:
        g.db_conn = get_pool().getconn()
    return g.db_conn

def db_query(sql, params=None, one=False):
    """Execute a SELECT and return dict-style rows."""
    conn = get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()

def db_exec(sql, params=None):
    """Execute a write statement (INSERT/UPDATE/DELETE)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def db_insert(sql, params=None):
    """Execute an INSERT and return the new row's id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql + ' RETURNING id', params)
            row_id = cur.fetchone()[0]
        conn.commit()
        return row_id
    except Exception:
        conn.rollback()
        raise

@app.teardown_appcontext
def return_db_connection(exc):
    """Return the connection to the pool at the end of every request."""
    conn = g.pop('db_conn', None)
    if conn is not None:
        if exc:
            conn.rollback()
        get_pool().putconn(conn)

def init_db():
    conn = psycopg2.connect(_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS kids (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    birth_year INTEGER,
                    avatar_color TEXT DEFAULT '#6366F1',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS sports (
                    id SERIAL PRIMARY KEY,
                    kid_id INTEGER NOT NULL REFERENCES kids(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    icon TEXT DEFAULT '🏅',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id SERIAL PRIMARY KEY,
                    sport_id INTEGER NOT NULL REFERENCES sports(id) ON DELETE CASCADE,
                    session_type TEXT NOT NULL,
                    date DATE NOT NULL,
                    skills_practiced TEXT,
                    mood_before INTEGER,
                    mood_after INTEGER,
                    energy_level TEXT,
                    competition_result TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS ai_insights (
                    id SERIAL PRIMARY KEY,
                    sport_id INTEGER UNIQUE NOT NULL REFERENCES sports(id) ON DELETE CASCADE,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    current_level TEXT,
                    progress_summary TEXT,
                    next_steps TEXT,
                    youtube_links TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS share_tokens (
                    id SERIAL PRIMARY KEY,
                    token TEXT UNIQUE NOT NULL,
                    sport_id INTEGER NOT NULL REFERENCES sports(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# AUTH HELPERS
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    if 'user_id' not in session:
        return None
    return db_query('SELECT * FROM users WHERE id = %s', (session['user_id'],), one=True)

def verify_kid_ownership(kid_id):
    return db_query(
        'SELECT * FROM kids WHERE id = %s AND user_id = %s',
        (kid_id, session['user_id']), one=True
    )

def verify_sport_ownership(sport_id):
    return db_query('''
        SELECT sp.*, k.user_id, k.name AS kid_name, k.id AS kid_id
        FROM sports sp
        JOIN kids k ON sp.kid_id = k.id
        WHERE sp.id = %s AND k.user_id = %s
    ''', (sport_id, session['user_id']), one=True)

def verify_session_ownership(session_id):
    return db_query('''
        SELECT se.*, sp.name AS sport_name, sp.id AS sport_id, k.user_id
        FROM sessions se
        JOIN sports sp ON se.sport_id = sp.id
        JOIN kids k ON sp.kid_id = k.id
        WHERE se.id = %s AND k.user_id = %s
    ''', (session_id, session['user_id']), one=True)

# ---------------------------------------------------------------------------
# AI INSIGHTS SIMULATION
# ---------------------------------------------------------------------------

def generate_youtube_links(sport_name, level, top_skills):
    sport_q = sport_name.lower().replace(' ', '+')
    level_q = level.lower()
    links = [
        {
            "title": f"{sport_name} {level} training for kids",
            "url": f"https://www.youtube.com/results?search_query={sport_q}+{level_q}+training+for+kids",
            "description": "Drills and exercises matched to their current level"
        },
        {
            "title": f"Youth {sport_name} motivation & mindset",
            "url": f"https://www.youtube.com/results?search_query=youth+{sport_q}+motivation+mindset",
            "description": "Building a healthy relationship with the sport"
        }
    ]
    if top_skills:
        skill_q = top_skills[0][0].lower().replace(' ', '+')
        links.insert(1, {
            "title": f"Improve {top_skills[0][0]} in {sport_name}",
            "url": f"https://www.youtube.com/results?search_query=improve+{skill_q}+{sport_q}+youth",
            "description": f"Focused practice on {top_skills[0][0]} — their most trained skill"
        })
    return links

def generate_ai_insights(sport_name, kid_name, sessions_data):
    session_count = len(sessions_data)

    if session_count == 0:
        return {
            "current_level": "No data yet",
            "progress_summary": f"No sessions logged yet for {kid_name}'s {sport_name}. Log at least 3 sessions to unlock AI insights.",
            "next_steps": ["Log your first session to begin tracking progress."],
            "youtube_links": generate_youtube_links(sport_name, "beginner", [])
        }

    training_count = sum(1 for s in sessions_data if s["session_type"] == "training")
    comp_count     = sum(1 for s in sessions_data if s["session_type"] == "competition")

    mood_scores  = [s["mood_after"] for s in sessions_data if s["mood_after"]]
    avg_mood     = round(sum(mood_scores) / len(mood_scores), 1) if mood_scores else 3.0

    recent_moods = [s["mood_after"] for s in sessions_data[-3:] if s["mood_after"]]
    older_moods  = [s["mood_after"] for s in sessions_data[:-3] if s["mood_after"]]
    if recent_moods and older_moods:
        diff = (sum(recent_moods) / len(recent_moods)) - (sum(older_moods) / len(older_moods))
        trend = "improving" if diff > 0.4 else ("dipping" if diff < -0.4 else "stable")
    else:
        trend = "stable"

    all_skills = []
    for s in sessions_data:
        if s["skills_practiced"]:
            try:
                skills = json.loads(s["skills_practiced"])
            except Exception:
                skills = [sk.strip() for sk in s["skills_practiced"].split(",") if sk.strip()]
            all_skills.extend(skills)

    skill_counts = {}
    for sk in all_skills:
        skill_counts[sk] = skill_counts.get(sk, 0) + 1
    top_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    sport_skill_list = SPORT_SKILLS.get(sport_name, DEFAULT_SKILLS)
    unpracticed = [s for s in sport_skill_list if s not in skill_counts]

    if session_count < 5:
        level, level_detail = "Beginner", "just getting started"
    elif session_count < 12:
        level, level_detail = "Developing", "building foundational skills"
    elif session_count < 25:
        level, level_detail = "Intermediate", "showing solid progress"
    elif session_count < 50:
        level, level_detail = "Advanced", "demonstrating strong capabilities"
    else:
        level, level_detail = "Expert", "operating at an elite level"

    mood_label   = {1: "struggling", 2: "below average", 3: "steady", 4: "positive", 5: "very positive"}.get(round(avg_mood), "steady")
    trend_phrase = {"improving": "and on an upward trajectory", "dipping": "but facing some recent challenges", "stable": "and consistent"}.get(trend, "and consistent")

    progress_summary = (
        f"{kid_name} has completed {session_count} {sport_name} session{'s' if session_count != 1 else ''} "
        f"({training_count} training, {comp_count} competition{'s' if comp_count != 1 else ''}), "
        f"{level_detail}. Engagement has been {mood_label} overall {trend_phrase}."
    )
    if top_skills:
        progress_summary += f" Most-practiced skill: {top_skills[0][0]}."
    if trend == "improving":
        progress_summary += f" The positive trend is great — {kid_name} seems to be in a productive phase."
    elif trend == "dipping":
        progress_summary += f" Consider exploring what's affecting motivation, and try a lighter, fun session."

    next_steps = []
    if level == "Beginner":
        next_steps.append("Focus on the fundamentals — consistency matters more than intensity right now.")
    elif level == "Developing":
        next_steps.append("Introduce structured drills and set small, measurable weekly goals.")
    elif level == "Intermediate":
        next_steps.append(f"Working with a coach to refine technique will accelerate progress at this stage.")
    else:
        next_steps.append(f"At {level.lower()} level, mental preparation and tactical awareness are as important as physical skills.")

    if unpracticed:
        next_steps.append(f"Skills not yet practiced: {', '.join(unpracticed[:2])}. Try adding these to upcoming sessions.")

    if comp_count == 0 and session_count >= 5:
        next_steps.append(f"With {session_count} training sessions, {kid_name} might be ready to try a friendly local event or competition.")

    if trend == "dipping":
        next_steps.append("Mix up the routine — a pressure-free, fun session can reset motivation and restore enthusiasm.")
    elif avg_mood >= 4:
        next_steps.append("High enjoyment levels are a great sign. Channel that energy by introducing new challenges.")

    return {
        "current_level": level,
        "progress_summary": progress_summary,
        "next_steps": next_steps,
        "youtube_links": generate_youtube_links(sport_name, level, top_skills)
    }

def generate_ai_insights_gemini(sport_name, kid_name, kid_age, sessions_data):
    """Generate insights via Google Gemini. Falls back to simulation if unavailable."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return generate_ai_insights(sport_name, kid_name, sessions_data)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        session_count   = len(sessions_data)
        training_count  = sum(1 for s in sessions_data if s['session_type'] == 'training')
        comp_count      = sum(1 for s in sessions_data if s['session_type'] == 'competition')

        all_skills = []
        for s in sessions_data:
            if s['skills_practiced']:
                try:
                    skills = json.loads(s['skills_practiced'])
                except Exception:
                    skills = [sk.strip() for sk in s['skills_practiced'].split(',') if sk.strip()]
                all_skills.extend(skills)
        skill_counts = {}
        for sk in all_skills:
            skill_counts[sk] = skill_counts.get(sk, 0) + 1

        mood_scores = [s['mood_after'] for s in sessions_data if s['mood_after']]
        avg_mood    = round(sum(mood_scores) / len(mood_scores), 1) if mood_scores else None

        recent_notes = [s['notes'] for s in sessions_data[-5:] if s['notes']]
        comp_results = [s['competition_result'] for s in sessions_data if s['competition_result']]

        age_str = f", {kid_age} years old" if kid_age else ""

        prompt = f"""You are an experienced youth sports development coach analysing a child's athletic progress.

Child: {kid_name}{age_str}
Sport: {sport_name}
Total sessions logged: {session_count} ({training_count} training, {comp_count} competitions)
Skills practiced (with frequency): {json.dumps(skill_counts) if skill_counts else 'None recorded yet'}
Average mood after sessions: {f'{avg_mood}/5' if avg_mood else 'Not recorded'} (1=very low, 5=very high)
Competition results: {', '.join(comp_results) if comp_results else 'No competitions yet'}
Recent coach/parent observations:
{chr(10).join(f'- {note}' for note in recent_notes) if recent_notes else '- No written observations yet'}

Analyse this data and return a JSON object with exactly these fields:
- "current_level": one of Beginner / Developing / Intermediate / Advanced / Expert
- "progress_summary": 2-3 sentences summarising progress, patterns, and mood trends. Be specific, warm, and honest.
- "next_steps": array of 3-4 concrete, actionable recommendations for the next 2-4 weeks
- "youtube_search_queries": array of 3 objects, each with "title" (short display label) and "search_query" (YouTube search string)

Return ONLY valid JSON. No markdown, no explanation, no code blocks.

Example:
{{"current_level":"Developing","progress_summary":"...","next_steps":["...","...","..."],"youtube_search_queries":[{{"title":"...","search_query":"..."}}]}}"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Strip markdown code fences if Gemini wraps the output
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        data = json.loads(text.strip())

        youtube_links = [
            {
                "title":       item.get("title", ""),
                "url":         "https://www.youtube.com/results?search_query=" + item.get("search_query", "").replace(" ", "+"),
                "description": item.get("title", "")
            }
            for item in data.get("youtube_search_queries", [])
        ]

        return {
            "current_level":    data.get("current_level", "Developing"),
            "progress_summary": data.get("progress_summary", ""),
            "next_steps":       data.get("next_steps", []),
            "youtube_links":    youtube_links
        }

    except Exception:
        # Any failure — network, parse error, quota — falls back to simulation
        return generate_ai_insights(sport_name, kid_name, sessions_data)

# ---------------------------------------------------------------------------
# ROUTES — AUTH
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = db_query('SELECT * FROM users WHERE email = %s', (email,), one=True)
        if user and check_password_hash(user['password_hash'], password):
            session['user_id']   = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('auth.html', mode='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not name or not email or not password:
            flash('All fields are required.', 'error')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
        else:
            try:
                user_id = db_insert(
                    'INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)',
                    (name, email, generate_password_hash(password))
                )
                session['user_id']   = user_id
                session['user_name'] = name
                return redirect(url_for('dashboard'))
            except psycopg2.errors.UniqueViolation:
                flash('An account with that email already exists.', 'error')
    return render_template('auth.html', mode='register')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# ROUTES — DASHBOARD
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def dashboard():
    kids_raw = db_query(
        'SELECT * FROM kids WHERE user_id = %s ORDER BY created_at ASC',
        (session['user_id'],)
    )
    kids_data = []
    for kid in kids_raw:
        sport_count = db_query(
            'SELECT COUNT(*) FROM sports WHERE kid_id = %s', (kid['id'],), one=True
        )['count']
        last_row = db_query('''
            SELECT MAX(se.date) AS last_date FROM sessions se
            JOIN sports sp ON se.sport_id = sp.id WHERE sp.kid_id = %s
        ''', (kid['id'],), one=True)
        kids_data.append({
            "id": kid['id'], "name": kid['name'],
            "birth_year": kid['birth_year'],
            "avatar_color": kid['avatar_color'],
            "sport_count": sport_count,
            "last_session": last_row['last_date'] if last_row else None
        })
    user = get_current_user()
    return render_template('dashboard.html', kids=kids_data, user=user)

# ---------------------------------------------------------------------------
# ROUTES — KIDS
# ---------------------------------------------------------------------------

@app.route('/kids/add', methods=['GET', 'POST'])
@login_required
def add_kid():
    if request.method == 'POST':
        name       = request.form.get('name', '').strip()
        birth_year = request.form.get('birth_year', '').strip()
        color      = AVATAR_COLORS[hash(name) % len(AVATAR_COLORS)]
        if not name:
            flash('Name is required.', 'error')
        else:
            db_insert(
                'INSERT INTO kids (user_id, name, birth_year, avatar_color) VALUES (%s, %s, %s, %s)',
                (session['user_id'], name, int(birth_year) if birth_year.isdigit() else None, color)
            )
            return redirect(url_for('dashboard'))
    return render_template('kid_form.html', action='add')

@app.route('/kids/<int:kid_id>')
@login_required
def kid_profile(kid_id):
    kid = verify_kid_ownership(kid_id)
    if not kid:
        return redirect(url_for('dashboard'))
    sports_raw = db_query(
        'SELECT * FROM sports WHERE kid_id = %s ORDER BY created_at ASC', (kid_id,)
    )
    sports_data = []
    for sp in sports_raw:
        session_count = db_query(
            'SELECT COUNT(*) FROM sessions WHERE sport_id = %s', (sp['id'],), one=True
        )['count']
        last_row = db_query(
            'SELECT MAX(date) AS last_date FROM sessions WHERE sport_id = %s', (sp['id'],), one=True
        )
        has_insights = db_query(
            'SELECT 1 FROM ai_insights WHERE sport_id = %s', (sp['id'],), one=True
        )
        sports_data.append({
            "id": sp['id'], "name": sp['name'], "icon": sp['icon'],
            "session_count": session_count,
            "last_session": last_row['last_date'] if last_row else None,
            "has_insights": bool(has_insights)
        })
    age = (datetime.now().year - kid['birth_year']) if kid['birth_year'] else None
    return render_template('kid.html', kid=kid, sports=sports_data, age=age, sport_limit=10)

@app.route('/kids/<int:kid_id>/sports/add', methods=['GET', 'POST'])
@login_required
def add_sport(kid_id):
    kid = verify_kid_ownership(kid_id)
    if not kid:
        return redirect(url_for('dashboard'))
    current_count = db_query(
        'SELECT COUNT(*) FROM sports WHERE kid_id = %s', (kid_id,), one=True
    )['count']
    if current_count >= 10:
        flash('A child can have a maximum of 10 sports.', 'error')
        return redirect(url_for('kid_profile', kid_id=kid_id))
    if request.method == 'POST':
        sport_name  = request.form.get('sport_name', '').strip()
        custom_name = request.form.get('custom_name', '').strip()
        name = custom_name if sport_name == '__custom__' else sport_name
        icon = SPORT_ICONS.get(name, '🏅')
        if not name:
            flash('Please select or enter a sport.', 'error')
        else:
            existing = db_query(
                'SELECT 1 FROM sports WHERE kid_id = %s AND name = %s', (kid_id, name), one=True
            )
            if existing:
                flash(f'{kid["name"]} already has {name} added.', 'error')
            else:
                db_insert(
                    'INSERT INTO sports (kid_id, name, icon) VALUES (%s, %s, %s)',
                    (kid_id, name, icon)
                )
                return redirect(url_for('kid_profile', kid_id=kid_id))
    return render_template('sport_form.html', kid=kid, sports_list=SPORTS, current_count=current_count)

# ---------------------------------------------------------------------------
# ROUTES — SPORT DETAIL & SESSIONS
# ---------------------------------------------------------------------------

@app.route('/sports/<int:sport_id>')
@login_required
def sport_detail(sport_id):
    sport = verify_sport_ownership(sport_id)
    if not sport:
        return redirect(url_for('dashboard'))
    sessions_raw = db_query(
        'SELECT * FROM sessions WHERE sport_id = %s ORDER BY date DESC, created_at DESC',
        (sport_id,)
    )
    insights_raw = db_query(
        'SELECT * FROM ai_insights WHERE sport_id = %s', (sport_id,), one=True
    )
    kid = db_query('SELECT * FROM kids WHERE id = %s', (sport['kid_id'],), one=True)

    sessions_list = []
    for s in sessions_raw:
        skills = []
        if s['skills_practiced']:
            try:
                skills = json.loads(s['skills_practiced'])
            except Exception:
                skills = [sk.strip() for sk in s['skills_practiced'].split(',') if sk.strip()]
        sessions_list.append({
            "id": s['id'], "session_type": s['session_type'], "date": s['date'],
            "skills": skills, "mood_before": s['mood_before'], "mood_after": s['mood_after'],
            "energy_level": s['energy_level'], "competition_result": s['competition_result'],
            "notes": s['notes']
        })

    insights_data = None
    if insights_raw:
        try:
            insights_data = {
                "current_level":    insights_raw['current_level'],
                "progress_summary": insights_raw['progress_summary'],
                "next_steps":       json.loads(insights_raw['next_steps']),
                "youtube_links":    json.loads(insights_raw['youtube_links']),
                "generated_at":     insights_raw['generated_at'].strftime('%Y-%m-%d %H:%M') if insights_raw['generated_at'] else ''
            }
        except Exception:
            insights_data = None

    mood_scores = [s['mood_after'] for s in sessions_list if s['mood_after']]
    avg_mood    = round(sum(mood_scores) / len(mood_scores), 1) if mood_scores else None

    return render_template(
        'sport.html',
        sport=sport, kid=kid,
        sessions=sessions_list,
        insights=insights_data,
        avg_mood=avg_mood,
        training_count=sum(1 for s in sessions_list if s['session_type'] == 'training'),
        comp_count=sum(1 for s in sessions_list if s['session_type'] == 'competition'),
        skill_suggestions=SPORT_SKILLS.get(sport['name'], DEFAULT_SKILLS)
    )

@app.route('/sports/<int:sport_id>/sessions/add', methods=['GET', 'POST'])
@login_required
def add_session(sport_id):
    sport = verify_sport_ownership(sport_id)
    if not sport:
        return redirect(url_for('dashboard'))
    kid = db_query('SELECT * FROM kids WHERE id = %s', (sport['kid_id'],), one=True)

    if request.method == 'POST':
        session_type = request.form.get('session_type', 'training')
        date_str     = request.form.get('date', '')
        skills_raw   = request.form.get('skills_practiced', '[]')
        mood_before  = request.form.get('mood_before') or None
        mood_after   = request.form.get('mood_after') or None
        energy_level = request.form.get('energy_level') or None
        comp_result  = request.form.get('competition_result') or None
        notes        = request.form.get('notes', '').strip() or None

        try:
            skills_list = json.loads(skills_raw)
            if not isinstance(skills_list, list):
                skills_list = [s.strip() for s in skills_raw.split(',') if s.strip()]
        except Exception:
            skills_list = [s.strip() for s in skills_raw.split(',') if s.strip()]

        if not date_str:
            flash('Please select a date.', 'error')
        else:
            db_insert('''
                INSERT INTO sessions
                (sport_id, session_type, date, skills_practiced, mood_before,
                 mood_after, energy_level, competition_result, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                sport_id, session_type, date_str,
                json.dumps(skills_list),
                int(mood_before) if mood_before else None,
                int(mood_after)  if mood_after  else None,
                energy_level, comp_result, notes
            ))
            return redirect(url_for('sport_detail', sport_id=sport_id))

    return render_template(
        'session_form.html',
        sport=sport, kid=kid,
        skill_suggestions=SPORT_SKILLS.get(sport['name'], DEFAULT_SKILLS),
        today=datetime.now().strftime('%Y-%m-%d')
    )

@app.route('/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
def delete_session(session_id):
    s = verify_session_ownership(session_id)
    if not s:
        return redirect(url_for('dashboard'))
    sport_id = s['sport_id']
    db_exec('DELETE FROM sessions WHERE id = %s', (session_id,))
    return redirect(url_for('sport_detail', sport_id=sport_id))

# ---------------------------------------------------------------------------
# ROUTES — AI INSIGHTS
# ---------------------------------------------------------------------------

@app.route('/sports/<int:sport_id>/insights/generate', methods=['POST'])
@login_required
def generate_insights(sport_id):
    sport = verify_sport_ownership(sport_id)
    if not sport:
        return jsonify({"error": "Not found"}), 404

    sessions_raw = db_query(
        'SELECT * FROM sessions WHERE sport_id = %s ORDER BY date ASC', (sport_id,)
    )
    kid = db_query('SELECT * FROM kids WHERE id = %s', (sport['kid_id'],), one=True)
    sessions_data = [dict(s) for s in sessions_raw]
    kid_age = (datetime.now().year - kid['birth_year']) if kid['birth_year'] else None
    insights = generate_ai_insights_gemini(sport['name'], kid['name'], kid_age, sessions_data)

    db_exec('''
        INSERT INTO ai_insights (sport_id, current_level, progress_summary, next_steps, youtube_links)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (sport_id) DO UPDATE SET
            current_level    = EXCLUDED.current_level,
            progress_summary = EXCLUDED.progress_summary,
            next_steps       = EXCLUDED.next_steps,
            youtube_links    = EXCLUDED.youtube_links,
            generated_at     = CURRENT_TIMESTAMP
    ''', (
        sport_id,
        insights['current_level'],
        insights['progress_summary'],
        json.dumps(insights['next_steps']),
        json.dumps(insights['youtube_links'])
    ))

    insights['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    return jsonify(insights)

# ---------------------------------------------------------------------------
# ROUTES — COACH SHARING
# ---------------------------------------------------------------------------

@app.route('/sports/<int:sport_id>/share', methods=['POST'])
@login_required
def create_share_link(sport_id):
    sport = verify_sport_ownership(sport_id)
    if not sport:
        return jsonify({"error": "Not found"}), 404
    # Reuse existing token if one exists
    existing = db_query('SELECT token FROM share_tokens WHERE sport_id = %s', (sport_id,), one=True)
    if existing:
        token = existing['token']
    else:
        token = secrets.token_urlsafe(16)
        db_insert('INSERT INTO share_tokens (token, sport_id) VALUES (%s, %s)', (token, sport_id))
    share_url = request.host_url.rstrip('/') + url_for('coach_view', token=token)
    return jsonify({"url": share_url})

@app.route('/coach/<token>')
def coach_view(token):
    row = db_query('SELECT * FROM share_tokens WHERE token = %s', (token,), one=True)
    if not row:
        return render_template('coach_view.html', error="This link is invalid or has expired."), 404

    sport_id = row['sport_id']
    sport    = db_query('SELECT * FROM sports WHERE id = %s', (sport_id,), one=True)
    kid      = db_query('SELECT * FROM kids WHERE id = %s', (sport['kid_id'],), one=True)

    sessions_raw = db_query(
        'SELECT * FROM sessions WHERE sport_id = %s ORDER BY date DESC', (sport_id,)
    )
    insights_raw = db_query('SELECT * FROM ai_insights WHERE sport_id = %s', (sport_id,), one=True)

    sessions_list = []
    for s in sessions_raw:
        skills = []
        if s['skills_practiced']:
            try:
                skills = json.loads(s['skills_practiced'])
            except Exception:
                skills = [sk.strip() for sk in s['skills_practiced'].split(',') if sk.strip()]
        sessions_list.append({
            "id": s['id'], "session_type": s['session_type'], "date": s['date'],
            "skills": skills, "mood_before": s['mood_before'], "mood_after": s['mood_after'],
            "energy_level": s['energy_level'], "competition_result": s['competition_result'],
            "notes": s['notes']
        })

    insights_data = None
    if insights_raw:
        try:
            insights_data = {
                "current_level":    insights_raw['current_level'],
                "progress_summary": insights_raw['progress_summary'],
                "next_steps":       json.loads(insights_raw['next_steps']),
                "youtube_links":    json.loads(insights_raw['youtube_links']),
                "generated_at":     insights_raw['generated_at'].strftime('%d %b %Y') if insights_raw['generated_at'] else ''
            }
        except Exception:
            insights_data = None

    mood_scores = [s['mood_after'] for s in sessions_list if s['mood_after']]
    avg_mood    = round(sum(mood_scores) / len(mood_scores), 1) if mood_scores else None

    return render_template(
        'coach_view.html',
        sport=sport, kid=kid,
        sessions=sessions_list,
        insights=insights_data,
        avg_mood=avg_mood,
        training_count=sum(1 for s in sessions_list if s['session_type'] == 'training'),
        comp_count=sum(1 for s in sessions_list if s['session_type'] == 'competition'),
        error=None
    )

# ---------------------------------------------------------------------------
# TEMPLATE FILTERS
# ---------------------------------------------------------------------------

@app.template_filter('mood_emoji')
def mood_emoji(val):
    return {1: '😞', 2: '😕', 3: '😐', 4: '🙂', 5: '😄'}.get(val, '—')

@app.template_filter('energy_label')
def energy_label(val):
    return {'low': '🔋 Low', 'medium': '⚡ Medium', 'high': '🔥 High'}.get(val or '', '—')

@app.template_filter('result_label')
def result_label(val):
    return {'win': '🏆 Win', 'loss': '❌ Loss', 'draw': '🤝 Draw', 'participation': '🎖️ Participated'}.get(val or '', '—')

@app.template_filter('format_date')
def format_date(val):
    if not val:
        return '—'
    try:
        if hasattr(val, 'strftime'):
            return val.strftime('%d %b %Y')
        return datetime.strptime(str(val), '%Y-%m-%d').strftime('%d %b %Y')
    except Exception:
        return str(val)

# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
