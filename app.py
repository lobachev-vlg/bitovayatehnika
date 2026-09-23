import os
from flask import Flask, render_template, request, redirect, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/request", methods=["POST"])
def make_request():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    device = request.form.get("device", "").strip()
    problem = request.form.get("problem", "").strip()

    if not name or not phone or not device or not problem:
        flash("Заполни все поля")
        return redirect("/")

    with open("requests.csv", "a", encoding="utf-8") as f:
        f.write(f'"{name}","{phone}","{device}","{problem}"\n')

    flash("Заявка отправлена")
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
