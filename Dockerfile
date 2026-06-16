FROM python:3.9-slim

EXPOSE 8501

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# שימוש במשתנה PORT ש‑Cloud Run מזריק (ברירת מחדל 8501)
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]