from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date
import boto3
import uuid
from boto3.dynamodb.conditions import Key, Attr

app = Flask(__name__)
app.secret_key = "your_secret_key"

#  AWS Setup
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')  # change AWS region if needed
sns_client = boto3.client('sns', region_name='us-east-1')
sns_topic_arn = 'arn:aws:sns:us-east-1:463470954496:medtrack-alerts'

# DynamoDB tables
users_table = dynamodb.Table('Users')
medications_table = dynamodb.Table('Medications')
doctor_table = dynamodb.Table('DoctorInfo')

#  Home Page
@app.route("/")
def home():
    return render_template("index.html")

# Login Page
@app.route("/login")
def login_page():
    return render_template("login.html")

#  Login Existing User
@app.route("/login-existing", methods=["POST"])
def login_existing():
    email = request.form["email"]
    password = request.form["password"]

    # DynamoDB doesn't allow direct equality search on non-key without GSI → scan
    response = users_table.scan(
        FilterExpression=Attr("email").eq(email)
    )
    users = response.get('Items', [])

    if not users or users[0]['password'] != password:
        return render_template("login.html", error="Invalid email or password")

    user = users[0]

    #  Store session values
    session["user_id"] = user["user_id"]
    session["username"] = user["name"]

    return redirect(url_for("dashboard"))

# Register New User
@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name")
    email = request.form.get("email")
    password = request.form.get("password")
    created_at = str(date.today())

    # Check if user already exists
    response = users_table.scan(
        FilterExpression=Attr("email").eq(email)
    )
    if response['Items']:
        return "❌ Email already registered. <a href='/login'>Login</a>"

    #  Save user to DynamoDB
    user_id = str(uuid.uuid4())
    users_table.put_item(Item={
        "user_id": user_id,
        "name": name,
        "email": email,
        "password": password,
        "created_at": created_at
    })

    return " Account created successfully! <a href='/login'>Login now</a>"

# Dashboard
from datetime import datetime

def format_date(d):
    """Convert YYYY-MM-DD → DD-MMM-YYYY (e.g. 2025-07-25 → 25-Jul-2025)"""
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d-%b-%Y")
    except Exception:
        return d  # fallback to original if parsing fails

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    username = session["username"]
    today = str(date.today())

    # Fetch ALL medications for this user
    response = medications_table.query(
        KeyConditionExpression=Key('user_id').eq(user_id)
    )
    all_meds = response.get('Items', [])

    # Filter today’s active meds (similar to MySQL WHERE start<=today<=end)
    today_meds = [
        m for m in all_meds
        if m['start_date'] <= today <= m['end_date']
    ]

    # ✅ Format dates for consistent display
    for med in all_meds:
        med["start_date"] = format_date(med["start_date"])
        med["end_date"] = format_date(med["end_date"])

    for med in today_meds:
        med["start_date"] = format_date(med["start_date"])
        med["end_date"] = format_date(med["end_date"])

    # Fetch doctor info (if exists)
    doc_response = doctor_table.get_item(Key={'user_id': user_id})
    doctor = doc_response.get('Item')

    # ✅ Format doctor’s next checkup date (if exists)
    if doctor and "next_checkup_date" in doctor:
        doctor["next_checkup_date"] = format_date(doctor["next_checkup_date"])

    return render_template(
        "dashboard.html",
        username=username,
        today_meds=today_meds,
        today_dose_count=len(today_meds),
        all_meds=all_meds,
        doctor=doctor
    )


#  Add Medicine
@app.route("/add-medicine", methods=["GET", "POST"])
def add_medicine():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        # Generate unique ID for the medicine
        medicine_id = str(uuid.uuid4())
        medicine_name = request.form["medicine_name"]
        dose_count = request.form["dose_count"]
        dose_time = request.form["dose_time"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        frequency = request.form["frequency"]

        # Store the medicine in DynamoDB
        medications_table.put_item(Item={
            "user_id": session["user_id"],
            "medicine_id": medicine_id,
            "medicine_name": medicine_name,
            "dose_count": dose_count,
            "dose_time": dose_time,
            "start_date": start_date,
            "end_date": end_date,
            "frequency": frequency
        })

        # Fetch user info
        user_id = session["user_id"]
        user_response = users_table.get_item(Key={'user_id': user_id})
        user = user_response.get("Item")

        if user and "email" in user:
            user_email = user["email"]

            try:
                # ✅ Check if user is already subscribed
                already_subscribed = user.get("sns_subscribed", False)

                if not already_subscribed:
                    # Subscribe the user's email ONLY ONCE
                    sns_client.subscribe(
                        TopicArn=sns_topic_arn,
                        Protocol='email',
                        Endpoint=user_email
                    )
                    print(f"✅ First-time SNS subscription email sent to {user_email}")

                    # ✅ Update user record so we don't subscribe again
                    users_table.update_item(
                        Key={'user_id': user_id},
                        UpdateExpression="set sns_subscribed = :val",
                        ExpressionAttributeValues={':val': True}
                    )
                else:
                    print(f"✅ User {user_email} already subscribed, skipping subscription")

                # ✅ Always publish a medicine-added notification
                sns_client.publish(
                    TopicArn=sns_topic_arn,
                    Subject="💊 MedTrack - Medicine Added",
                    Message=(
                        f"Hello {user['name']},\n\n"
                        f"You have successfully added the medicine '{medicine_name}' to your MedTrack account.\n"
                        f"Start Date: {start_date}\n"
                        f"End Date: {end_date}\n"
                        f"Dose Time: {dose_time}\n\n"
                        f"Stay healthy!\n– MedTrack"
                    )
                )

            except Exception as e:
                print("❌ SNS Error:", str(e))

        return redirect(url_for("dashboard"))

    return render_template("add_medicine.html")



#  Edit Medicine
@app.route("/edit-medicine/<medicine_id>", methods=["GET", "POST"])
def edit_medicine(medicine_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Fetch medicine
    response = medications_table.get_item(Key={'user_id': user_id, 'medicine_id': medicine_id})
    medicine = response.get('Item')

    if not medicine:
        return "❌ Medicine not found!", 404

    if request.method == "POST":
        #  Overwrite updated item
        medications_table.put_item(Item={
            "user_id": user_id,
            "medicine_id": medicine_id,
            "medicine_name": request.form["medicine_name"],
            "dose_count": request.form["dose_count"],
            "dose_time": request.form["dose_time"],
            "start_date": request.form["start_date"],
            "end_date": request.form["end_date"],
            "frequency": request.form["frequency"]
        })
        return redirect(url_for("dashboard"))

    return render_template("edit_medicine.html", medicine=medicine)

#  Delete Medicine
@app.route("/delete-medicine/<medicine_id>", methods=["POST"])
def delete_medicine(medicine_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    medications_table.delete_item(
        Key={"user_id": session["user_id"], "medicine_id": medicine_id}
    )
    return redirect(url_for("dashboard"))

#  Doctor Info
@app.route("/doctor-info", methods=["GET", "POST"])
def doctor_info():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    #  Fetch existing doctor details
    doc_response = doctor_table.get_item(Key={'user_id': user_id})
    doctor = doc_response.get('Item')

    if request.method == "POST":
        #  Upsert doctor info
        doctor_table.put_item(Item={
            "user_id": user_id,
            "name": request.form["name"],
            "specialization": request.form["specialization"],
            "phone": request.form["phone"],
            "email": request.form["email"],
            "next_checkup_date": request.form["next_checkup_date"]
        })
        return redirect(url_for("dashboard"))

    return render_template("doctor_info.html", doctor=doctor)

#  User Profile
@app.route("/user")
def user_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    response = users_table.get_item(Key={'user_id': user_id})
    user = response.get('Item')

    return render_template("user_profile.html", username=user["name"], email=user["email"])

#  Logout
@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
