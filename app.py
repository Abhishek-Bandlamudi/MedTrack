from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from datetime import date

app = Flask(__name__)
app.secret_key = "your_secret_key"  # needed for sessions

# ✅ MySQL connection details
db_config = {
    "host": "localhost",
    "user": "root",           # change if needed
    "password": "",
    "database": "medtrack_db"
}

# ✅ Helper function to get DB connection
def get_db_connection():
    return mysql.connector.connect(**db_config)

# ✅ Home Page
@app.route("/")
def home():
    return render_template("index.html")

# ✅ Login/Signup Page
@app.route("/login")
def login_page():
    return render_template("login.html")

# ✅ Handle Existing User Login
@app.route("/login-existing", methods=["POST"])
def login_existing():
    email = request.form["email"]
    password = request.form["password"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    # User not found OR wrong password
    if not user or user["password"] != password:
        return render_template("login.html", error="Invalid email or password")

    # ✅ Store session values
    session["user_id"] = user["id"]
    session["username"] = user["name"]

    # ✅ Redirect to dashboard
    return redirect(url_for("dashboard"))

# ✅ Handle New User Registration
@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name")
    email = request.form.get("email")
    password = request.form.get("password")
    created_at = date.today()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, email, password, created_at) VALUES (%s, %s, %s, %s)",
            (name, email, password, created_at)
        )
        conn.commit()
        conn.close()
        return "✅ Account created successfully! <a href='/login'>Login now</a>"
    except mysql.connector.Error as err:
        if err.errno == 1062:  # Duplicate email
            return "❌ Email already registered. <a href='/login'>Login</a>"
        else:
            return f"❌ Database error: {err}"

# ✅ Dashboard
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    username = session["username"]
    today = date.today()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ✅ Fetch ONLY today's medicines (active between start_date & end_date)
    cursor.execute("""
        SELECT * FROM medications 
        WHERE user_id=%s 
          AND start_date <= %s 
          AND end_date >= %s
    """, (user_id, today, today))
    today_meds = cursor.fetchall()

    # ✅ Fetch ALL medications for this user
    cursor.execute("SELECT * FROM medications WHERE user_id=%s ORDER BY start_date DESC", (user_id,))
    all_meds = cursor.fetchall()

    # ✅ Fetch doctor info (if exists)
    cursor.execute("SELECT * FROM doctor_info WHERE user_id=%s", (user_id,))
    doctor = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "dashboard.html",
        username=username,
        today_meds=today_meds,
        today_dose_count=len(today_meds),  # count for “Today’s Doses”
        all_meds=all_meds,  # full medication list for "Your Medications"
        doctor=doctor
    )


# ✅ Show Add Medicine Form
@app.route("/add-medicine", methods=["GET", "POST"])
def add_medicine():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        medicine_name = request.form["medicine_name"]
        dose_count = request.form["dose_count"]
        dose_time = request.form["dose_time"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        frequency = request.form["frequency"]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO medications (user_id, medicine_name, dose_count, dose_time, start_date, end_date, frequency)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (session["user_id"], medicine_name, dose_count, dose_time, start_date, end_date, frequency))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for("dashboard"))

    return render_template("add_medicine.html")

# ✅ Edit Medicine Route
@app.route("/edit-medicine/<int:med_id>", methods=["GET", "POST"])
def edit_medicine(med_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch medicine details
    cursor.execute("SELECT * FROM medications WHERE id=%s AND user_id=%s", (med_id, session["user_id"]))
    medicine = cursor.fetchone()

    if not medicine:
        cursor.close()
        conn.close()
        return "❌ Medicine not found!", 404

    if request.method == "POST":
        medicine_name = request.form["medicine_name"]
        dose_count = request.form["dose_count"]
        dose_time = request.form["dose_time"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        frequency = request.form["frequency"]

        cursor.execute("""
            UPDATE medications
            SET medicine_name=%s, dose_count=%s, dose_time=%s, start_date=%s, end_date=%s, frequency=%s
            WHERE id=%s AND user_id=%s
        """, (medicine_name, dose_count, dose_time, start_date, end_date, frequency, med_id, session["user_id"]))

        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("dashboard"))

    cursor.close()
    conn.close()
    return render_template("edit_medicine.html", medicine=medicine)

# ✅ Delete Medicine Route
@app.route("/delete-medicine/<int:med_id>", methods=["POST"])
def delete_medicine(med_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM medications WHERE id=%s AND user_id=%s", (med_id, session["user_id"]))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("dashboard"))

@app.route("/doctor-info", methods=["GET", "POST"])
def doctor_info():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch existing doctor details (if any)
    cursor.execute("SELECT * FROM doctor_info WHERE user_id=%s", (user_id,))
    doctor = cursor.fetchone()

    if request.method == "POST":
        name = request.form["name"]
        specialization = request.form["specialization"]
        phone = request.form["phone"]
        email = request.form["email"]
        next_checkup_date = request.form["next_checkup_date"]

        if doctor:
            # Update existing record
            cursor.execute("""
                UPDATE doctor_info 
                SET name=%s, specialization=%s, phone=%s, email=%s, next_checkup_date=%s 
                WHERE user_id=%s
            """, (name, specialization, phone, email, next_checkup_date, user_id))
        else:
            # Insert new record
            cursor.execute("""
                INSERT INTO doctor_info (user_id, name, specialization, phone, email, next_checkup_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, name, specialization, phone, email, next_checkup_date))

        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("dashboard"))

    cursor.close()
    conn.close()
    return render_template("doctor_info.html", doctor=doctor)

@app.route("/user")
def user_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template("user_profile.html", username=user["name"], email=user["email"])

# ✅ Logout Route
@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
