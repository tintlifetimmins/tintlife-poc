from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "alive", "message": "Tintlife backend is running"}
