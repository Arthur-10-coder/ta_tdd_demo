from fastapi import FastAPI
import requests, os
MOCK_BASE = os.getenv("MOCK_BASE","http://mockoon:3000")
app = FastAPI()

@app.get("/health") 
def health(): return {"ok": True}

@app.get("/greeting")
def greeting():
    r = requests.get(f"{MOCK_BASE}/api/greeting", timeout=3)
    r.raise_for_status()
    return {"msg": r.json().get("msg")}
