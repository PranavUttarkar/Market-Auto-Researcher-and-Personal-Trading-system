"""
ATLAS AI Hedge Fund — Autonomous Multi-Asset Trading
=====================================================
Entry point.  Runs on port 5002.
    python ai_hedge_fund.py
    → http://127.0.0.1:5002
"""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

from fund import ai_config as cfg
from fund.ai_fund_engine import AIFundEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("atlas")

# ── Flask app ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
)
app.config["SECRET_KEY"] = "atlas-ai-fund-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

engine = AIFundEngine(emit_fn=socketio.emit)


@app.route("/")
def dashboard():
    return render_template("ai_dashboard.html", config={
        "instruments": cfg.INSTRUMENTS,
        "initial_balance": cfg.INITIAL_BALANCE,
        "agents": list(cfg.AGENT_WEIGHTS.keys()),
        "paper": True,
    })


@app.route("/api/state")
def api_state():
    return jsonify(engine.get_latest_update())


@socketio.on("connect")
def on_connect():
    log.info("Dashboard client connected")
    state = engine.get_latest_update()
    if state:
        socketio.emit("update", state)


# ── Main ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 64)
    log.info("  ATLAS AI HEDGE FUND — Autonomous Multi-Asset Trading")
    log.info(f"  Balance : ${cfg.INITIAL_BALANCE:,.0f}")
    log.info(f"  Agents  : {', '.join(cfg.AGENT_WEIGHTS.keys())}")
    instr = ", ".join(i["symbol"] for i in cfg.INSTRUMENTS)
    log.info(f"  Assets  : {instr}")
    log.info(f"  AI Model: {cfg.AI_MODEL} @ {cfg.AI_BASE_URL}")
    log.info(f"  Dashboard: http://127.0.0.1:{cfg.DASHBOARD_PORT}")
    log.info("=" * 64)

    engine.start()
    socketio.run(
        app,
        host=cfg.DASHBOARD_HOST,
        port=cfg.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
