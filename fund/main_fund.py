"""
AI-Native Hedge Fund — Paper Trading Entry Point

Multi-agent, multi-instrument paper trading fund.
Run from project root:  python fund/main_fund.py
Open: http://127.0.0.1:5001
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

from fund import config as fund_config
from fund.fund_engine import FundEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static"))
app.config["SECRET_KEY"] = "fund-paper-dev"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

engine = FundEngine(emit_fn=socketio.emit)


@app.route("/")
@app.route("/fund")
def dashboard():
    return render_template("fund_dashboard.html", config={
        "instruments": fund_config.INSTRUMENTS,
        "initial_balance": fund_config.INITIAL_BALANCE,
        "paper": True,
    })


@app.route("/api/fund/state")
def api_state():
    return jsonify(engine.get_latest_update())


@socketio.on("connect")
def on_connect():
    log.info("Fund dashboard client connected")
    socketio.emit("update", engine.get_latest_update())


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  AI-NATIVE HEDGE FUND (Paper Trading)")
    instr_str = ", ".join(f"{i['symbol']} {i['timeframe']}" for i in fund_config.INSTRUMENTS)
    log.info(f"  Instruments: {instr_str}")
    log.info(f"  Balance: ${fund_config.INITIAL_BALANCE:,.2f}")
    log.info(f"  Dashboard: http://{fund_config.DASHBOARD_HOST}:{fund_config.DASHBOARD_PORT}/fund")
    log.info("=" * 60)

    engine.start()
    socketio.run(
        app,
        host=fund_config.DASHBOARD_HOST,
        port=fund_config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
