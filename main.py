"""
Crypto Paper Trading Bot — Entry Point

Run:  python main.py
Open: http://127.0.0.1:5000

Everything starts here: the trading engine, strategy loop, and live dashboard.
"""

import logging
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

import config
from paper_engine import PaperEngine
from trader import Trader

# ── Logging ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Flask + SocketIO ────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = "paper-trader-dev"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── Trading Components ──────────────────────────────────────────────────

engine = PaperEngine()
trader = Trader(engine=engine, emit_fn=socketio.emit)

# ── Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html", config={
        "symbol": config.SYMBOL,
        "timeframe": config.TIMEFRAME,
        "initial_balance": config.INITIAL_BALANCE,
        "paper": config.PAPER_TRADING,
    })


@app.route("/api/state")
def api_state():
    """REST endpoint — reliable fallback for dashboard data."""
    return jsonify(trader.get_latest_update())


@socketio.on("connect")
def on_connect():
    log.info("Dashboard client connected via WebSocket")
    socketio.emit("update", trader.get_latest_update())


# ── Start ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  CRYPTO PAPER TRADING BOT")
    log.info(f"  Symbol: {config.SYMBOL} | Timeframe: {config.TIMEFRAME}")
    log.info(f"  Mode: {'PAPER' if config.PAPER_TRADING else 'LIVE'}")
    log.info(f"  Balance: ${config.INITIAL_BALANCE:,.2f}")
    log.info(f"  Dashboard: http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    log.info("=" * 60)

    # Start trading loop in background thread
    trader.start()

    # Start web server (blocks)
    socketio.run(
        app,
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
