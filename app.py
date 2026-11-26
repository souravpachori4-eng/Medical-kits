import os
import io
import numpy as np
import pandas as pd
from flask import Flask, request, redirect, url_for, flash, render_template_string
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

app = Flask(__name__)
app.secret_key = "change-this-local-secret"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(BASE_DIR, "liver_dataset.csv")

# These are the 9 input columns used by your original script:
# df.iloc[:,  2:11] -> Age, TB, DB, Alkphos, SGPT, SGOT, TP, ALB, A/G Ratio
FEATURES = [
    ("Age", "Age", "e.g. 45", 0.1),
    ("Total Bilirubin", "Total Bilirubin", "e.g. 0.8", 0.01),
    ("Direct Bilirubin", "Direct Bilirubin", "e.g. 0.2", 0.01),
    ("Alkaline Phosphotase", "Alkaline Phosphotase", "e.g. 200", 0.1),
    ("SGPT", "SGPT", "e.g. 30", 0.1),
    ("SGOT", "SGOT", "e.g. 35", 0.1),
    ("Total Proteins", "Total Proteins", "e.g. 6.8", 0.01),
    ("Albumin", "Albumin", "e.g. 3.5", 0.01),
    ("A/G Ratio", "A/G Ratio", "e.g. 1.0", 0.01),
]

model = None
feature_columns = []
target_values = []
accuracy = None
matrix = None
row_count = 0
error_message = None


def train_model(path=DATASET_PATH):
    global model, feature_columns, target_values, accuracy, matrix, row_count, error_message
    model = None
    error_message = None
    try:
        df = pd.read_csv(path)
        if "Result" not in df.columns:
            raise ValueError("Your CSV must contain a column named 'Result'.")

        # Match the feature selection in your original model.
        x = df.iloc[:, 2:11].copy()
        y = df["Result"].copy()

        if x.shape[1] != 9:
            raise ValueError(
                "Expected 9 input columns in CSV positions 3 to 11. "
                "Please check that your dataset has the same column structure as your original file."
            )

        feature_columns = list(x.columns)
        x = x.apply(pd.to_numeric, errors="coerce")
        y = y.astype(str)
        valid = y.notna()
        x, y = x.loc[valid], y.loc[valid]
        if len(x) < 5:
            raise ValueError("Dataset has too few usable rows. Please upload a larger CSV file.")

        pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", DecisionTreeClassifier(random_state=42, class_weight="balanced"))
        ])

        # Keep a test set aside for a meaningful evaluation.
        stratify = y if y.value_counts().min() >= 2 else None
        try:
            x_train, x_test, y_train, y_test = train_test_split(
                x, y, test_size=0.2, random_state=42, stratify=stratify
            )
        except ValueError:
            x_train, x_test, y_train, y_test = train_test_split(
                x, y, test_size=0.2, random_state=42
            )

        evaluation_model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", DecisionTreeClassifier(random_state=42, class_weight="balanced"))
        ])
        evaluation_model.fit(x_train, y_train)
        predictions = evaluation_model.predict(x_test)
        accuracy = accuracy_score(y_test, predictions) * 100
        labels = sorted(y.unique().tolist())
        matrix = confusion_matrix(y_test, predictions, labels=labels).tolist()

        # Train final model on all available rows for the live prediction form.
        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", DecisionTreeClassifier(random_state=42, class_weight="balanced"))
        ])
        model.fit(x, y)
        target_values = labels
        row_count = len(df)
    except Exception as exc:
        error_message = str(exc)


def class_description(value):
    v = str(value).strip().lower()
    if v in ("1", "1.0"):
        return "Liver disease class predicted"
    if v in ("2", "2.0"):
        return "Non-liver-disease class predicted"
    return "Predicted class: " + str(value)


PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HepatoCare | Liver Risk Prediction</title>
<style>
:root{--navy:#10243a;--blue:#2867e8;--teal:#13b8a6;--ink:#17283d;--muted:#718096;--bg:#f3f7fc;--line:#e5edf6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Arial,Helvetica,sans-serif;color:var(--ink)}
.top{background:linear-gradient(115deg,#10243a,#173e63);color:white;padding:22px max(22px,calc((100% - 1120px)/2));display:flex;align-items:center;justify-content:space-between;gap:15px}
.brand{display:flex;align-items:center;gap:12px}.logo{width:44px;height:44px;border-radius:14px;background:#ffffff1c;display:grid;place-items:center;font-size:24px}
.brand h1{font-size:19px;margin:0 0 4px}.brand p{margin:0;color:#c4d5e7;font-size:12px}.pill{font-size:12px;border:1px solid #ffffff45;border-radius:30px;padding:8px 12px;color:#dcecff}
.wrap{max-width:1120px;margin:28px auto;padding:0 18px}.intro{margin-bottom:22px}.intro h2{font-size:27px;margin:0 0 7px;color:#142b45}.intro p{margin:0;color:var(--muted);line-height:1.5}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin-bottom:20px}.stat,.panel{background:white;border:1px solid var(--line);border-radius:17px;box-shadow:0 7px 22px #18385b08}
.stat{padding:17px 19px}.stat .label{font-size:12px;color:var(--muted);margin-bottom:8px}.stat strong{font-size:24px;color:#18324e}.stat small{display:block;color:#91a0b1;font-size:11px;margin-top:5px}
.layout{display:grid;grid-template-columns:1.35fr .85fr;gap:18px;align-items:start}.panel{padding:22px}.panel-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}.panel h3{margin:0;font-size:17px;color:#18324e}.step{font-size:11px;color:var(--blue);background:#edf3ff;padding:6px 10px;border-radius:30px}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:14px}.field label{display:block;font-size:12px;font-weight:700;color:#42556c;margin-bottom:7px}.field input{width:100%;border:1px solid #dce6f1;border-radius:10px;padding:12px 11px;font-size:14px;outline:none;background:#fbfdff;color:#1d3047}.field input:focus{border-color:#5c8ff2;box-shadow:0 0 0 3px #2867e815}
.btn{border:0;border-radius:11px;padding:13px 18px;font-weight:700;font-size:14px;cursor:pointer;background:linear-gradient(100deg,#2867e8,#3c85f4);color:white;box-shadow:0 7px 15px #2867e82b}.btn:hover{filter:brightness(1.04)}.submit{width:100%;margin-top:18px}.hint{font-size:11px;color:#8a99aa;line-height:1.5;margin:12px 0 0}
.sidebox{background:linear-gradient(150deg,#edf7ff,#f7fbff);border:1px solid #deebf8;border-radius:14px;padding:17px;margin-bottom:14px}.sidebox h4{margin:0 0 9px;color:#23415f;font-size:14px}.sidebox p{font-size:12px;line-height:1.6;color:#657b91;margin:0}
.result{border-radius:14px;padding:18px;margin-bottom:14px;background:#eefaf7;border:1px solid #ccefe6}.result.warning{background:#fff8eb;border-color:#f5e1b6}.result .tag{font-size:11px;font-weight:700;color:#0b8b79;text-transform:uppercase;letter-spacing:.5px}.result h4{font-size:19px;margin:8px 0;color:#153e3b}.result p{font-size:12px;line-height:1.55;color:#59736f;margin:0}
.upload{border:1px dashed #b9cce0;background:#f9fbfe;border-radius:13px;padding:16px}.upload input{width:100%;font-size:12px;margin:8px 0 12px}.upload .btn{padding:10px 14px;font-size:12px}
.alert{padding:12px 14px;border-radius:10px;background:#fff1f0;color:#a53c35;font-size:12px;margin-bottom:15px;line-height:1.5}
.footer{text-align:center;color:#93a1b1;font-size:11px;padding:25px 10px 35px;line-height:1.6}
@media(max-width:760px){.layout{grid-template-columns:1fr}.stats{gap:9px}.stat{padding:13px}.stat strong{font-size:20px}.top{padding:17px 18px}.pill{display:none}.intro h2{font-size:23px}}
@media(max-width:420px){.fields{grid-template-columns:1fr}.wrap{margin-top:20px}.panel{padding:17px}.stats{grid-template-columns:1fr 1fr}.stats .stat:last-child{grid-column:span 2}}
</style>
</head>
<body>
<header class="top">
 <div class="brand"><div class="logo">✚</div><div><h1>HepatoCare</h1><p>Liver health prediction dashboard</p></div></div>
 <div class="pill">ML-powered educational screening tool</div>
</header>
<main class="wrap">
 <section class="intro"><h2>Liver Disease Prediction</h2><p>Enter the patient's laboratory values to view the prediction from your trained machine learning model.</p></section>
 {% if error %}<div class="alert"><b>Dataset problem:</b> {{ error }}<br>Upload the correct CSV below. It must contain a <b>Result</b> column and the 9 feature columns in the same order as your original dataset.</div>{% endif %}
 <section class="stats">
  <div class="stat"><div class="label">MODEL ACCURACY</div><strong>{% if accuracy is not none %}{{ "%.1f"|format(accuracy) }}%{% else %}--{% endif %}</strong><small>Held-out test data</small></div>
  <div class="stat"><div class="label">TRAINING RECORDS</div><strong>{% if row_count %}{{ row_count }}{% else %}--{% endif %}</strong><small>Rows loaded from CSV</small></div>
  <div class="stat"><div class="label">MODEL TYPE</div><strong style="font-size:19px">Decision Tree</strong><small>Scikit-learn classifier</small></div>
 </section>
 <section class="layout">
  <div class="panel">
   <div class="panel-head"><h3>Patient information</h3><span class="step">9 INPUT VALUES</span></div>
   <form method="POST" action="/predict">
    <div class="fields">
     {% for f in fields %}
     <div class="field"><label for="f{{ loop.index0 }}">{{ f[0] }}</label><input id="f{{ loop.index0 }}" name="v{{ loop.index0 }}" type="number" step="any" placeholder="{{ f[2] }}" required value="{{ values[loop.index0] if values else '' }}"></div>
     {% endfor %}
    </div>
    <button class="btn submit" type="submit" {% if not ready %}disabled style="opacity:.5"{% endif %}>✦ &nbsp; Predict result</button>
    <p class="hint">Enter values from the patient's laboratory report. All 9 fields are required.</p>
   </form>
   {% if prediction is not none %}
   <div style="margin-top:18px" class="result {% if prediction|string in ['1','1.0'] %}warning{% endif %}">
    <div class="tag">Model prediction</div><h4>{{ description }}</h4>
    <p>Predicted dataset class: <b>{{ prediction }}</b>. This is an automated model output, not a medical diagnosis.</p>
   </div>
   {% endif %}
  </div>
  <aside class="panel">
   <div class="panel-head"><h3>Model overview</h3><span class="step">ABOUT</span></div>
   <div class="sidebox"><h4>How it works</h4><p>The app loads your liver patient CSV, trains a Decision Tree model, evaluates it on a held-out test split, and uses the trained model to predict the entered values.</p></div>
   <div class="sidebox"><h4>Input parameters</h4><p>Age, Total Bilirubin, Direct Bilirubin, Alkaline Phosphotase, SGPT, SGOT, Total Proteins, Albumin and A/G Ratio.</p></div>
   <div class="upload"><h4 style="margin:0;color:#29435e;font-size:14px">Upload your dataset</h4><p style="font-size:11px;color:#8192a5;margin:5px 0">Choose your liver patient training CSV file.</p>
    <form action="/upload" method="POST" enctype="multipart/form-data"><input type="file" name="dataset" accept=".csv" required><button class="btn" type="submit">Upload & train model</button></form>
   </div>
   {% if matrix %}
   <div style="margin-top:16px"><h4 style="font-size:13px;margin:0 0 8px">Confusion matrix</h4><p style="font-size:11px;color:#8292a4;margin:0 0 8px">Rows = actual class, columns = predicted class</p>
   <div style="display:grid;grid-template-columns:repeat({{ matrix|length }},1fr);gap:5px">{% for row in matrix %}{% for cell in row %}<div style="background:#edf3ff;border-radius:7px;text-align:center;padding:10px;font-weight:bold;color:#2856a2">{{ cell }}</div>{% endfor %}{% endfor %}</div></div>
   {% endif %}
  </aside>
 </section>
 <div class="footer">Educational project · Flask + Python + Scikit-learn<br>Not intended for clinical diagnosis or treatment decisions.</div>
</main>
</body></html>
"""


@app.route("/", methods=["GET"])
def home():
    return render_template_string(
        PAGE, fields=FEATURES, accuracy=accuracy, row_count=row_count,
        matrix=matrix, error=error_message, ready=(model is not None),
        prediction=None, description=None, values=None
    )


@app.route("/predict", methods=["POST"])
def predict():
    if model is None:
        flash("Please upload your training CSV dataset first.")
        return redirect(url_for("home"))
    try:
        vals = [float(request.form[f"v{i}"]) for i in range(9)]
        row = pd.DataFrame([vals], columns=feature_columns)
        pred = str(model.predict(row)[0])
        return render_template_string(
            PAGE, fields=FEATURES, accuracy=accuracy, row_count=row_count,
            matrix=matrix, error=error_message, ready=True,
            prediction=pred, description=class_description(pred),
            values=[str(v) for v in vals]
        )
    except Exception as exc:
        return render_template_string(
            PAGE, fields=FEATURES, accuracy=accuracy, row_count=row_count,
            matrix=matrix, error="Prediction error: " + str(exc), ready=True,
            prediction=None, description=None, values=None
        )


@app.route("/upload", methods=["POST"])
def upload():
    global error_message
    uploaded = request.files.get("dataset")
    if not uploaded or not uploaded.filename.lower().endswith(".csv"):
        error_message = "Please select a CSV file."
        return redirect(url_for("home"))
    try:
        uploaded.save(DATASET_PATH)
        train_model(DATASET_PATH)
    except Exception as exc:
        error_message = str(exc)
    return redirect(url_for("home"))


if __name__ == "__main__":
    if os.path.exists(DATASET_PATH):
        train_model(DATASET_PATH)
    print("\\nHepatoCare is starting...")
    print("Open this address in your phone browser: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
