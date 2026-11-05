import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# En Render, apuntá DB_PATH a un Persistent Disk (ej: /data/trading_data.db).
# Sin disco persistente, el archivo se borra en cada deploy/reinicio.
DB_PATH = os.getenv("DB_PATH", "trading_data.db")
API_KEY = os.getenv("API_KEY", "")  # Opcional en Render > Environment

app = FastAPI(title="Trading Dashboard Backend")

# allow_credentials=True junto con "*" no es válido; no usamos cookies, así que va en False.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y.%m.%d %H:%M:%S",  # formato de TimeToString() en MT4/MT5
    "%Y-%m-%dT%H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M",
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT NOT NULL,
                magic INTEGER DEFAULT 0,
                broker TEXT DEFAULT '',
                account TEXT DEFAULT '',
                ticket INTEGER NOT NULL,
                symbol TEXT,
                type TEXT,
                profit REAL,
                balance_after REAL,
                timestamp TEXT
            )
        """)
        
        # Migración: agrega columnas nuevas si la tabla ya existía sin ellas
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
        for col, ddl in (
            ("magic", "INTEGER DEFAULT 0"),
            ("broker", "TEXT DEFAULT ''"),
            ("account", "TEXT DEFAULT ''"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {ddl}")
        
        # El ticket es único dentro de una cuenta, no entre brókers distintos
        conn.execute("DROP INDEX IF EXISTS ux_trades_ticket")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_bot_ticket ON trades(bot_id, ticket)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_account_ticket "
            "ON trades(account, ticket) WHERE account <> ''"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_trades_ts ON trades(timestamp)")


init_db()


def check_api_key(x_api_key: str = Header(default="")):
    if API_KEY and not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="API key inválida")


def normalize_ts(value: Optional[str]) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    value = value.strip().rstrip("Z")
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise HTTPException(status_code=422, detail=f"Formato de timestamp no reconocido: {value}")


class Trade(BaseModel):
    bot_id: str
    magic: int = 0
    broker: str = ""    # opcional: "deriv" / "icmarkets"
    account: str = ""   # opcional: número de cuenta
    ticket: int
    symbol: str
    type: str
    profit: float
    balance_after: float
    timestamp: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/trade")
def receive_trade(trade: Trade):
    ts = normalize_ts(trade.timestamp)
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO trades
                (bot_id, magic, broker, account, ticket, symbol, type, profit, balance_after, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.bot_id.strip(), 
                trade.magic, 
                trade.broker.strip().lower(), 
                trade.account.strip(),
                trade.ticket, 
                trade.symbol.strip(), 
                trade.type.strip().upper(),
                trade.profit, 
                trade.balance_after, 
                ts,
            ),
        )
        inserted = cur.rowcount > 0

    if not inserted:
        return {"status": "ignored", "message": "El ticket ya fue registrado anteriormente"}
    return {"status": "success", "message": "Trade guardado correctamente"}


@app.get("/api/trades")
def get_trades():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY timestamp ASC, id ASC").fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
