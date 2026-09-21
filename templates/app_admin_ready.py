from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from sklearn.linear_model import LinearRegression
from datetime import datetime, date, timedelta
import random
import os
import smtplib
from email.message import EmailMessage

app = Flask(__name__)

app.secret_key = "smart-study-planner-secret-key"

DATABASE = "study_planner.db"

# =========================================================
# ADMIN SETTINGS
# =========================================================
# Change these later if you want a different admin login.
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin@123"


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_db():

    conn = get_db()
    cursor = conn.cursor()

    # -----------------------------------------------------
    # USERS TABLE
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL,

            daily_goal REAL DEFAULT 2,

            email TEXT,
            otp TEXT,
            otp_expiry TEXT,
            role TEXT DEFAULT 'user'

        )
    """)

    # -----------------------------------------------------
    # ACTIVITY / LOGIN TRACKING TABLE
    # -----------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            activity TEXT NOT NULL,
            page TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # -----------------------------------------------------
    # STUDY PLANS TABLE
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_plans (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            subject TEXT NOT NULL,

            date TEXT NOT NULL,

            hours REAL NOT NULL,

            status TEXT DEFAULT 'Pending',

            studied_hours REAL DEFAULT 0,

            FOREIGN KEY(user_id)
            REFERENCES users(id)

        )
    """)

    # -----------------------------------------------------
    # OLD DATABASE COMPATIBILITY
    # -----------------------------------------------------

    cursor.execute("""
        PRAGMA table_info(users)
    """)

    user_columns = [
        column[1]
        for column in cursor.fetchall()
    ]

    if "daily_goal" not in user_columns:

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN daily_goal REAL DEFAULT 2
        """)

    if "email" not in user_columns:

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN email TEXT
        """)

    if "otp" not in user_columns:

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN otp TEXT
        """)

    if "otp_expiry" not in user_columns:

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN otp_expiry TEXT
        """)

    # Add role column to older databases
    cursor.execute("""
        PRAGMA table_info(users)
    """)
    user_columns = [column[1] for column in cursor.fetchall()]

    if "role" not in user_columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN role TEXT DEFAULT 'user'
        """)

    # Create a default admin account if it does not exist.
    cursor.execute("""
        SELECT id FROM users WHERE username = ?
    """, (ADMIN_USERNAME,))
    admin_exists = cursor.fetchone()

    if not admin_exists:
        cursor.execute("""
            INSERT INTO users (username, password, daily_goal, email, role)
            VALUES (?, ?, ?, ?, ?)
        """, (
            ADMIN_USERNAME,
            generate_password_hash(ADMIN_PASSWORD),
            2,
            None,
            "admin"
        ))
    else:
        cursor.execute("""
            UPDATE users SET role = 'admin'
            WHERE username = ?
        """, (ADMIN_USERNAME,))

    cursor.execute("""
        PRAGMA table_info(study_plans)
    """)

    plan_columns = [
        column[1]
        for column in cursor.fetchall()
    ]

    if "user_id" not in plan_columns:

        cursor.execute("""
            ALTER TABLE study_plans
            ADD COLUMN user_id INTEGER
        """)

    if "status" not in plan_columns:

        cursor.execute("""
            ALTER TABLE study_plans
            ADD COLUMN status TEXT DEFAULT 'Pending'
        """)

    if "studied_hours" not in plan_columns:

        cursor.execute("""
            ALTER TABLE study_plans
            ADD COLUMN studied_hours REAL DEFAULT 0
        """)

    # Fix old NULL values

    cursor.execute("""
        UPDATE study_plans

        SET studied_hours = 0

        WHERE studied_hours IS NULL
    """)

    cursor.execute("""
        UPDATE users

        SET daily_goal = 2

        WHERE daily_goal IS NULL
    """)

    conn.commit()
    conn.close()


# =========================================================
# ML PERFORMANCE PREDICTION
# =========================================================

def predict_performance(planned_hours, studied_hours):

    try:

        planned_hours = float(planned_hours)

        studied_hours = float(studied_hours)

        if planned_hours <= 0:

            return 0

        # Calculate completion percentage

        completion_rate = (
            studied_hours / planned_hours
        ) * 100

        completion_rate = max(
            0,
            min(completion_rate, 100)
        )

        # Sample training data

        training_completion = [

            [0],
            [10],
            [20],
            [30],
            [40],
            [50],
            [60],
            [70],
            [80],
            [90],
            [100]

        ]

        training_scores = [

            35,
            38,
            42,
            46,
            50,
            55,
            61,
            67,
            74,
            82,
            90

        ]

        model = LinearRegression()

        model.fit(
            training_completion,
            training_scores
        )

        prediction = model.predict(
            [[completion_rate]]
        )[0]

        prediction = max(
            0,
            min(prediction, 100)
        )

        return round(prediction)

    except Exception:

        return 0


# =========================================================
# STUDY STREAK
# =========================================================

def calculate_streak(completed_dates):

    if not completed_dates:

        return 0

    today = date.today()

    # Streak starts from today.
    # If no study today, current streak is 0.

    if today not in completed_dates:

        return 0

    streak = 0

    current_day = today

    while current_day in completed_dates:

        streak += 1

        current_day -= timedelta(days=1)

    return streak


# =========================================================
# ADMIN / ACTIVITY HELPERS
# =========================================================

def log_activity(activity, page=None, user_id=None, username=None):
    """Store a simple activity record for the admin dashboard."""
    try:
        if user_id is None:
            user_id = session.get("user_id")
        if username is None:
            username = session.get("username")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_logs
            (user_id, username, activity, page, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            username,
            activity,
            page,
            datetime.now().isoformat(timespec="seconds")
        ))
        conn.commit()
        conn.close()
    except Exception:
        # Tracking must never break the student's application.
        pass


@app.before_request
def track_user_activity():
    # Count authenticated page visits/interactions.
    if session.get("user_id") and session.get("role") != "admin":
        endpoint = request.endpoint or ""
        ignored = {
            "static",
            "admin_login",
            "admin_dashboard",
            "admin_logout"
        }
        if endpoint not in ignored:
            log_activity(
                "Page visit",
                request.path,
                session.get("user_id"),
                session.get("username")
            )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "home.html"
    )


# =========================================================
# EMAIL / OTP HELPERS
# =========================================================

def send_otp_email(to_email, otp, purpose="verification"):

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        return False, "Email service is not configured. Please set SMTP_USER and SMTP_PASSWORD."

    subject = "Smart Study Planner - Your OTP"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = to_email
    message.set_content(
        f"Your Smart Study Planner OTP for {purpose} is: {otp}\n\n"
        "This OTP is valid for 10 minutes. If you did not request it, you can ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)
        return True, None
    except Exception as exc:
        return False, str(exc)


def generate_otp():
    return str(random.randint(100000, 999999))


def otp_expiry_time():
    return (datetime.now() + timedelta(minutes=10)).isoformat()


# =========================================================
# SIGNUP
# =========================================================

@app.route(
    "/signup",
    methods=["GET", "POST"]
)
def signup():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not username or not email or not password:
            return render_template(
                "signup.html",
                error="Please fill in username, email and password."
            )

        if "@" not in email or "." not in email.split("@")[-1]:
            return render_template(
                "signup.html",
                error="Please enter a valid email address."
            )

        if len(password) < 6:
            return render_template(
                "signup.html",
                error="Password must be at least 6 characters long."
            )

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        existing_username = cursor.fetchone()
        cursor.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
        existing_email = cursor.fetchone()
        conn.close()

        if existing_username:
            return render_template("signup.html", error="Username already exists.")

        if existing_email:
            return render_template("signup.html", error="Email already registered.")

        otp = generate_otp()
        session["pending_signup"] = {
            "username": username,
            "email": email,
            "password": password,
            "otp": otp,
            "otp_expiry": otp_expiry_time()
        }

        # OTP is generated for verification.
        # Email sending is intentionally not required in this version.
        return redirect(url_for("verify_signup_otp"))

    return render_template("signup.html")


@app.route(
    "/verify_signup_otp",
    methods=["GET", "POST"]
)
def verify_signup_otp():

    pending = session.get("pending_signup")
    if not pending:
        return redirect(url_for("signup"))

    if request.method == "POST":
        otp = request.form.get("otp", "").strip()

        if datetime.now() > datetime.fromisoformat(pending["otp_expiry"]):
            return render_template("verify_otp.html", error="OTP expired. Please sign up again.", demo_otp=pending["otp"], email=pending["email"])

        if otp != pending["otp"]:
            return render_template("verify_otp.html", error="Invalid OTP. Please try again.", demo_otp=pending["otp"], email=pending["email"])

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (username, password, daily_goal, email, role)
                VALUES (?, ?, ?, ?, ?)
            """, (
                pending["username"],
                generate_password_hash(pending["password"]),
                2,
                pending["email"],
                "user"
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            session.pop("pending_signup", None)
            return render_template("signup.html", error="Username or email already exists.")
        conn.close()
        session.pop("pending_signup", None)
        return redirect(url_for("login"))

    return render_template("verify_otp.html", demo_otp=pending["otp"], email=pending["email"])


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        ).strip()

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM users

            WHERE username = ?
        """, (
            username,
        ))

        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"] or "user"

            log_activity(
                "Login",
                "/login",
                user["id"],
                user["username"]
            )

            if session["role"] == "admin":
                return redirect(url_for("admin_dashboard"))

            return redirect(
                url_for("dashboard")
            )

        return render_template(
            "login.html",
            error="Invalid username or password."
        )

    return render_template(
        "login.html"
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    username = session["username"]

    conn = get_db()
    cursor = conn.cursor()

    # -----------------------------------------------------
    # USER
    # -----------------------------------------------------

    cursor.execute("""
        SELECT *
        FROM users

        WHERE id = ?
    """, (
        user_id,
    ))

    user = cursor.fetchone()

    daily_goal = float(
        user["daily_goal"] or 2
    )

    # -----------------------------------------------------
    # STUDY PLANS
    # -----------------------------------------------------

    cursor.execute("""
        SELECT *
        FROM study_plans

        WHERE user_id = ?

        ORDER BY date DESC, id DESC
    """, (
        user_id,
    ))

    plans = cursor.fetchall()

    conn.close()

    # -----------------------------------------------------
    # TOTAL SUBJECTS
    # -----------------------------------------------------

    subjects = set()

    for plan in plans:

        subjects.add(
            plan["subject"]
        )

    total_subjects = len(subjects)

    # -----------------------------------------------------
    # TOTAL PLANNED HOURS
    # -----------------------------------------------------

    total_hours = sum(

        float(
            plan["hours"] or 0
        )

        for plan in plans

    )

    # -----------------------------------------------------
    # TOTAL ACTUAL STUDIED HOURS
    # -----------------------------------------------------

    studied_hours = sum(

        float(
            plan["studied_hours"] or 0
        )

        for plan in plans

    )

    completed_hours = studied_hours

    # -----------------------------------------------------
    # REMAINING HOURS
    # -----------------------------------------------------

    pending_hours = max(
        0,
        total_hours - studied_hours
    )

    # -----------------------------------------------------
    # OVERALL PROGRESS
    # -----------------------------------------------------

    if total_hours > 0:

        progress = (
            studied_hours / total_hours
        ) * 100

    else:

        progress = 0

    progress = round(
        max(
            0,
            min(progress, 100)
        ),
        1
    )

    # -----------------------------------------------------
    # ML PERFORMANCE
    # -----------------------------------------------------

    expected_score = predict_performance(
        total_hours,
        studied_hours
    )

    # -----------------------------------------------------
    # TODAY'S STUDIED HOURS
    # -----------------------------------------------------

    today_string = date.today().isoformat()

    today_hours = 0

    for plan in plans:

        if plan["date"] == today_string:

            today_hours += float(
                plan["studied_hours"] or 0
            )

    today_hours = round(
        today_hours,
        1
    )

    # -----------------------------------------------------
    # DAILY GOAL PROGRESS
    # -----------------------------------------------------

    if daily_goal > 0:

        goal_progress = (
            today_hours / daily_goal
        ) * 100

    else:

        goal_progress = 0

    goal_progress = round(
        max(
            0,
            min(goal_progress, 100)
        ),
        1
    )

    # -----------------------------------------------------
    # STUDY STREAK
    # -----------------------------------------------------

    completed_dates = set()

    for plan in plans:

        studied = float(
            plan["studied_hours"] or 0
        )

        if studied > 0:

            try:

                completed_date = datetime.strptime(
                    plan["date"],
                    "%Y-%m-%d"
                ).date()

                completed_dates.add(
                    completed_date
                )

            except ValueError:

                pass

    streak = calculate_streak(
        completed_dates
    )

    # -----------------------------------------------------
    # SUBJECT-WISE PROGRESS
    # -----------------------------------------------------

    subject_data = {}

    for plan in plans:

        subject = plan["subject"]

        if subject not in subject_data:

            subject_data[subject] = {
                "planned": 0,
                "studied": 0
            }

        subject_data[subject]["planned"] += float(
            plan["hours"] or 0
        )

        subject_data[subject]["studied"] += float(
            plan["studied_hours"] or 0
        )

    subject_progress = []

    for subject, data in subject_data.items():

        planned = data["planned"]

        studied = data["studied"]

        if planned > 0:

            percentage = (
                studied / planned
            ) * 100

        else:

            percentage = 0

        percentage = round(
            max(
                0,
                min(percentage, 100)
            ),
            1
        )

        subject_progress.append({

            "subject": subject,

            "planned": round(
                planned,
                1
            ),

            "studied": round(
                studied,
                1
            ),

            "progress": percentage

        })

    # -----------------------------------------------------
    # CHART DATA
    # -----------------------------------------------------

    chart_labels = []

    chart_values = []

    for item in subject_progress:

        chart_labels.append(
            item["subject"]
        )

        chart_values.append(
            item["studied"]
        )

    chart_data = {

        "labels": chart_labels,

        "values": chart_values

    }

    # -----------------------------------------------------
    # RANDOM MOTIVATIONAL QUOTE
    # -----------------------------------------------------

    motivational_quotes = [

        "Small progress every day leads to big results. 📚💜",

        "You don't need to be perfect. You just need to keep going. 🌱",

        "One focused hour today can make tomorrow easier. ⏰✨",

        "Your future self will thank you for the effort you make today. 🌟",

        "Dream big, start small, and never stop learning. 🚀",

        "Every difficult topic becomes easier when you give it time. 🧠📖",

        "Slow progress is still progress. Keep moving forward. 🌸",

        "Discipline will take you where motivation cannot. 🔥",

        "Keep showing up. Your hard work is adding up. 💪",

        "Believe in your effort, even when the results take time. 💜",

        "A little study today is better than a lot of regret tomorrow. 📚",

        "Don't compare your chapter 1 with someone else's chapter 20. 🌱",

        "Focus on progress, not perfection. ✨",

        "The secret to getting ahead is getting started. 🚀",

        "Your goals are possible when your daily actions support them. 🎯",

        "Study now, shine later. 🌟",

        "Every page you read is one step closer to your goal. 📖",

        "Consistency beats intensity when it comes to learning. 🔥",

        "You are capable of learning more than you think. 🧠",

        "Make today's effort count. Your future is being built right now. 💪"

    ]

    motivation_emojis = [

        "🌱",
        "🔥",
        "📚",
        "💪",
        "🌟",
        "🚀",
        "🧠",
        "✨",
        "🎯",
        "💜"

    ]

    random_quote = random.choice(
        motivational_quotes
    )

    random_motivation_emoji = random.choice(
        motivation_emojis
    )

    # -----------------------------------------------------
    # RENDER DASHBOARD
    # -----------------------------------------------------

    return render_template(

        "dashboard.html",

        plans=plans,

        username=username,

        total_subjects=total_subjects,

        total_hours=round(
            total_hours,
            1
        ),

        studied_hours=round(
            studied_hours,
            1
        ),

        completed_hours=round(
            completed_hours,
            1
        ),

        pending_hours=round(
            pending_hours,
            1
        ),

        progress=progress,

        expected_score=expected_score,

        subject_progress=subject_progress,

        chart_data=chart_data,

        daily_goal=round(
            daily_goal,
            1
        ),

        today_hours=today_hours,

        goal_progress=goal_progress,

        streak=streak,

        random_quote=random_quote,

        random_motivation_emoji=random_motivation_emoji

    )


# =========================================================
# SET DAILY GOAL
# =========================================================

@app.route(
    "/set_goal",
    methods=["POST"]
)
def set_goal():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    try:

        daily_goal = float(
            request.form.get(
                "daily_goal",
                2
            )
        )

    except ValueError:

        daily_goal = 2

    if daily_goal <= 0:

        daily_goal = 2

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users

        SET daily_goal = ?

        WHERE id = ?
    """, (
        daily_goal,
        user_id
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# ADD STUDY PLAN
# =========================================================

@app.route(
    "/add_plan",
    methods=["POST"]
)
def add_plan():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    subject = request.form.get(
        "subject",
        ""
    ).strip()

    study_date = request.form.get(
        "date",
        ""
    ).strip()

    try:

        planned_hours = float(
            request.form.get(
                "hours",
                0
            )
        )

    except ValueError:

        planned_hours = 0

    if planned_hours < 0:

        planned_hours = 0

    # A newly created study plan has
    # zero actual study hours.
    # Actual study time will be added later
    # using the Update Study option.

    studied_hours = 0

    status = "Pending"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO study_plans
        (
            user_id,
            subject,
            date,
            hours,
            status,
            studied_hours
        )

        VALUES (?, ?, ?, ?, ?, ?)
    """, (

        user_id,

        subject,

        study_date,

        planned_hours,

        status,

        studied_hours

    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# UPDATE ACTUAL STUDY HOURS
# =========================================================

@app.route(
    "/update_study/<int:plan_id>",
    methods=["POST"]
)
def update_study(plan_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    try:

        studied_hours = float(
            request.form.get(
                "studied_hours",
                0
            )
        )

    except ValueError:

        studied_hours = 0

    if studied_hours < 0:

        studied_hours = 0

    conn = get_db()
    cursor = conn.cursor()

    # Get the selected plan belonging to
    # the currently logged-in user.
    cursor.execute("""
        SELECT hours
        FROM study_plans

        WHERE id = ?

        AND user_id = ?
    """, (
        plan_id,
        user_id
    ))

    plan = cursor.fetchone()

    if plan:

        planned_hours = float(
            plan["hours"] or 0
        )

        # Actual study time cannot be more
        # than the planned study time.
        if studied_hours > planned_hours:

            studied_hours = planned_hours

        if (
            planned_hours > 0
            and
            studied_hours >= planned_hours
        ):

            status = "Completed"

        else:

            status = "Pending"

        cursor.execute("""
            UPDATE study_plans

            SET

                studied_hours = ?,

                status = ?

            WHERE id = ?

            AND user_id = ?
        """, (
            studied_hours,
            status,
            plan_id,
            user_id
        ))

        conn.commit()

    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# EDIT STUDY PLAN
# =========================================================

@app.route(
    "/edit/<int:plan_id>",
    methods=["GET", "POST"]
)
def edit_plan(plan_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    conn = get_db()
    cursor = conn.cursor()

    # -----------------------------------------------------
    # SAVE EDITED PLAN
    # -----------------------------------------------------

    if request.method == "POST":

        subject = request.form.get(
            "subject",
            ""
        ).strip()

        study_date = request.form.get(
            "date",
            ""
        ).strip()

        try:

            planned_hours = float(
                request.form.get(
                    "hours",
                    0
                )
            )

        except ValueError:

            planned_hours = 0

        if planned_hours < 0:

            planned_hours = 0

        # Keep the already recorded actual study hours.
        # Actual study time is changed only through
        # the Update Study option on the dashboard.

        cursor.execute("""
            SELECT studied_hours
            FROM study_plans

            WHERE id = ?

            AND user_id = ?
        """, (
            plan_id,
            user_id
        ))

        existing_plan = cursor.fetchone()

        if existing_plan:

            studied_hours = float(
                existing_plan["studied_hours"] or 0
            )

        else:

            studied_hours = 0

        # If planned hours are reduced below the
        # already studied hours, cap actual hours
        # to the new planned amount.

        if studied_hours > planned_hours:

            studied_hours = planned_hours

        if (
            planned_hours > 0
            and
            studied_hours >= planned_hours
        ):

            status = "Completed"

        else:

            status = "Pending"

        cursor.execute("""
            UPDATE study_plans

            SET

                subject = ?,

                date = ?,

                hours = ?,

                studied_hours = ?,

                status = ?

            WHERE id = ?

            AND user_id = ?
        """, (

            subject,

            study_date,

            planned_hours,

            studied_hours,

            status,

            plan_id,

            user_id

        ))

        conn.commit()
        conn.close()

        return redirect(
            url_for("dashboard")
        )

    # -----------------------------------------------------
    # OPEN EDIT PAGE
    # -----------------------------------------------------

    cursor.execute("""
        SELECT *

        FROM study_plans

        WHERE id = ?

        AND user_id = ?
    """, (
        plan_id,
        user_id
    ))

    plan = cursor.fetchone()

    conn.close()

    if not plan:

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "edit_plan.html",
        plan=plan
    )


# =========================================================
# DELETE STUDY PLAN
# =========================================================

@app.route(
    "/delete/<int:plan_id>",
    methods=["POST"]
)
def delete_plan(plan_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM study_plans

        WHERE id = ?

        AND user_id = ?
    """, (
        plan_id,
        user_id
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )



# =========================================================
# FORGOT PASSWORD + EMAIL OTP
# =========================================================

@app.route(
    "/forgot_password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()

        if not email:
            return render_template("forgot_password.html", error="Please enter your email address.")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE lower(email) = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return render_template("forgot_password.html", error="No account found with this email.")

        otp = generate_otp()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET otp = ?, otp_expiry = ? WHERE id = ?", (otp, otp_expiry_time(), user["id"]))
        conn.commit()
        conn.close()

        # OTP is generated for password reset.
        # Email sending is intentionally not required in this version.
        session["reset_user_id"] = user["id"]
        session["reset_email"] = email
        return redirect(url_for("verify_reset_otp"))

    return render_template("forgot_password.html")


@app.route(
    "/verify_reset_otp",
    methods=["GET", "POST"]
)
def verify_reset_otp():

    if "reset_user_id" not in session:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT otp, otp_expiry FROM users WHERE id = ?", (session["reset_user_id"],))
        user = cursor.fetchone()
        conn.close()

        if not user or not user["otp"] or not user["otp_expiry"]:
            return render_template("verify_otp.html", error="OTP not found. Please request a new OTP.", reset_mode=True, demo_otp=user["otp"] if user else "", email=session.get("reset_email", ""))

        if datetime.now() > datetime.fromisoformat(user["otp_expiry"]):
            return render_template("verify_otp.html", error="OTP expired. Please request a new OTP.", reset_mode=True, demo_otp=user["otp"], email=session.get("reset_email", ""))

        if otp != user["otp"]:
            return render_template("verify_otp.html", error="Invalid OTP. Please try again.", reset_mode=True, demo_otp=user["otp"], email=session.get("reset_email", ""))

        session["reset_verified"] = True
        return redirect(url_for("reset_password"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT otp FROM users WHERE id = ?", (session["reset_user_id"],))
    reset_user = cursor.fetchone()
    conn.close()
    return render_template("verify_otp.html", reset_mode=True, demo_otp=reset_user["otp"] if reset_user else "", email=session.get("reset_email", ""))


@app.route(
    "/reset_password",
    methods=["GET", "POST"]
)
def reset_password():

    if not session.get("reset_verified") or "reset_user_id" not in session:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not new_password or not confirm_password:
            return render_template("reset_password.html", error="Please fill in both password fields.")

        if len(new_password) < 6:
            return render_template("reset_password.html", error="Password must be at least 6 characters long.")

        if new_password != confirm_password:
            return render_template("reset_password.html", error="Passwords do not match.")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password = ?, otp = NULL, otp_expiry = NULL WHERE id = ?", (generate_password_hash(new_password), session["reset_user_id"]))
        conn.commit()
        conn.close()

        session.pop("reset_user_id", None)
        session.pop("reset_email", None)
        session.pop("reset_verified", None)
        return redirect(url_for("login"))

    return render_template("reset_password.html")


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, role FROM users WHERE username = ?",
                (ADMIN_USERNAME,)
            )
            admin = cursor.fetchone()
            conn.close()

            if admin:
                session.clear()
                session["user_id"] = admin["id"]
                session["username"] = admin["username"]
                session["role"] = "admin"

                log_activity(
                    "Admin login",
                    "/admin/login",
                    admin["id"],
                    admin["username"]
                )
                return redirect(url_for("admin_dashboard"))

        return render_template(
            "admin_login.html",
            error="Invalid admin username or password."
        )

    return render_template("admin_login.html")


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
def admin_dashboard():

    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role != 'admin'")
    total_users = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM activity_logs
        WHERE activity = 'Login'
    """)
    total_logins = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(DISTINCT user_id) AS total
        FROM activity_logs
        WHERE activity = 'Login' AND user_id IS NOT NULL
    """)
    unique_logins = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM activity_logs
        WHERE activity = 'Page visit'
    """)
    total_interactions = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM study_plans
    """)
    total_plans = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT
            username,
            COUNT(*) AS interactions,
            MAX(created_at) AS last_seen
        FROM activity_logs
        WHERE username IS NOT NULL AND username != ?
        GROUP BY username
        ORDER BY interactions DESC
        LIMIT 20
    """, (ADMIN_USERNAME,))
    user_activity = cursor.fetchall()

    cursor.execute("""
        SELECT username, activity, page, created_at
        FROM activity_logs
        WHERE username IS NOT NULL
        ORDER BY id DESC
        LIMIT 30
    """)
    recent_activity = cursor.fetchall()

    cursor.execute("""
        SELECT id, username, email, role
        FROM users
        WHERE role != 'admin'
        ORDER BY id DESC
        LIMIT 50
    """)
    users = cursor.fetchall()

    conn.close()

    return render_template(
        "admin.html",
        total_users=total_users,
        total_logins=total_logins,
        unique_logins=unique_logins,
        total_interactions=total_interactions,
        total_plans=total_plans,
        user_activity=user_activity,
        recent_activity=recent_activity,
        users=users
    )


# =========================================================
# ADMIN LOGOUT
# =========================================================

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    init_db()

app.run(host="0.0.0.0", port=5000,
            debug=True
    )
    