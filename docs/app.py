from flask import Flask, render_template, request, redirect, flash
import csv
import os

app = Flask(__name__)
app.secret_key = "secret-key"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    name = request.form.get("name")
    phone = request.form.get("phone")
    device = request.form.get("device")
    problem = request.form.get("problem")

    file_exists = os.path.isfile("requests.csv")
    with open("requests.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["name", "phone", "device", "problem"])
        writer.writerow([name, phone, device, problem])

    flash("Заявка отправлена!")
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
