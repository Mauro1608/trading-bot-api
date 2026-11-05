from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
from datetime import datetime

app = FastAPI(title="Trading Dashboard Backend")

# Permitir conexiones desde cualquier origen (para que las VPS puedan enviar datos)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar base de datos SQLite
def init_db():
    conn = sqlite3.connect("trading_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT,
            magic INTEGER,
            ticket INTEGER,
            symbol TEXT,
            type TEXT,
            profit REAL,
            balance_after REAL,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

class Trade(BaseModel):
    bot_id: str
    magic: int = 0  # <--- Nuevo campo para el Número Mágico
    ticket: int
    symbol: str
    type: str
    profit: float
    balance_after: float
    timestamp: str = None

@app.post("/api/trade")
def receive_trade(trade: Trade):
    if not trade.timestamp:
        trade.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect("trading_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trades (bot_id, magic, ticket, symbol, type, profit, balance_after, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (trade.bot_id, trade.magic, trade.ticket, trade.symbol, trade.type, trade.profit, trade.balance_after, trade.timestamp))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Trade guardado correctamente"}

@app.get("/api/trades")
def get_trades():
    conn = sqlite3.connect("trading_data.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
