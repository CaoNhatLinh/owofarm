# This file is part of owo-dusk.
#
# Copyright (c) 2024-present EchoQuill
#
# Portions of this file are based on code by EchoQuill, licensed under the
# GNU General Public License v3.0 (GPL-3.0).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import logging
import random
import sqlite3
import sys
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request

from utils.runtime_handler import load_weekly_runtime
from utils import bot_control
from utils import quick_sale_jobs
from utils import rare_catches
from utils import gamble_session
from utils import account_setup
from utils.timestamp import get_weekday

app = Flask(__name__)
website_logs = []
config_updated = None

# these will be updated
password = ""
version = ""


@app.before_request
def local_only():
    # Credentials are editable without a password; accept loopback requests only.
    allowed = {"localhost", "127.0.0.1", "::1"}
    try:
        host = urlsplit("http://" + request.host).hostname
        origin = request.headers.get("Origin")
        origin_host = urlsplit(origin).hostname if origin else None
    except ValueError:
        return "Local access only", 403
    if request.remote_addr not in {"127.0.0.1", "::1"} or host not in allowed or (origin and origin_host not in allowed):
        return "Local access only", 403


def merge_dicts(main, small):
    for key, value in small.items():
        if key in main and isinstance(main[key], dict) and isinstance(value, dict):
            merge_dicts(main[key], value)
        else:
            main[key] = value


def get_from_db(command):
    with sqlite3.connect("utils/data/db.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        if mode.lower() != "wal":
            cur.execute("PRAGMA journal_mode=WAL;")

        cur.execute(command)

        item = cur.fetchall()
        return item


@app.route("/")
def home():
    return render_template("index.html", version=version,
                           weapon_sale_ranks=quick_sale_jobs.WEAPON_RANKS,
                           animal_sale_ranks=quick_sale_jobs.ANIMAL_RANKS)


@app.route("/api/console", methods=["GET"])
def get_console_logs():
    try:
        log_string = "\n".join(website_logs)
        return log_string
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return jsonify(
            {"status": "error", "message": "An error occurred while fetching logs"}
        ), 500


@app.route("/api/bot", methods=["GET", "POST"])
def control_bot():
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("action") not in ("start", "stop"):
            return jsonify(status="error", message="Action must be start or stop"), 400
        bot_control.set_running(data["action"] == "start")
    response = jsonify(status="success", running=bot_control.is_running(),
                       resumeRequest=bot_control.get_resume_generation(),
                       settings=bot_control.get_settings(), accounts=bot_control.get_runtimes())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/settings", methods=["GET", "PATCH"])
def dashboard_settings():
    if request.method == "PATCH":
        try:
            values = bot_control.validate_settings(request.get_json(silent=True))
            requested_channel = values.get("channelId", "")
            if requested_channel and requested_channel != bot_control.get_settings()["channelId"]:
                bot_control.validate_channel(requested_channel)
            bot_control.update_settings(values)
        except ValueError as exc:
            return jsonify(status="error", message=str(exc)), 400
        except OSError:
            return jsonify(status="error", message="Không lưu được cấu hình. Thử lại sau."), 500
    response = jsonify(status="success", settings=bot_control.get_settings())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/account", methods=["GET", "PUT"])
def account_credentials():
    if request.content_length and request.content_length > 4096:
        return jsonify(status="error", message="Dữ liệu quá dài."), 413
    try:
        channel_applied = False
        if request.method == "PUT":
            channel_applied = account_setup.save(request.get_json(silent=True))
        accounts = account_setup.read_accounts()
        single = accounts[0] if len(accounts) == 1 else ["", ""]
        response = jsonify(status="success", token=single[0], channelId=single[1],
                           multiple=len(accounts) > 1,
                           channelApplied=channel_applied,
                           restartRequired=account_setup.PENDING_PATH.exists())
        response.headers["Cache-Control"] = "no-store"
        return response
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400
    except OSError:
        return jsonify(status="error", message="Không đọc/ghi được file tài khoản."), 500


@app.route("/api/gamble/simulate", methods=["POST"])
def simulate_coinflip():
    from utils.coinflip_simulation import validate, compare
    from utils.coinflip_history import load
    try:
        data = validate(request.get_json(silent=True))
        accounts = {str(a.get("accountId")) for a in bot_control.get_runtimes() if a.get("accountId")}
        if data["accountId"] not in accounts:
            raise ValueError("Chọn tài khoản đang kết nối để đọc lịch sử.")
        result = compare(load(data["accountId"]).rows, data)
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response
    except ValueError as error:
        return jsonify(message=str(error)), 400
    except sqlite3.Error:
        return jsonify(message="Chưa đọc được file lịch sử. Hãy thử lại."), 503


@app.route("/api/gamble/reset", methods=["POST"])
def reset_gamble_session():
    try:
        result = gamble_session.submit_reset(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400
    except TimeoutError as exc:
        return jsonify(status="error", message=str(exc)), 504
    return jsonify(status="success", **result)


@app.route("/api/catches", methods=["GET"])
def catch_statistics():
    response = jsonify(status="success", **rare_catches.snapshot())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/sales", methods=["GET", "POST"])
def quick_sales():
    if request.method == "POST":
        try:
            job = quick_sale_jobs.submit(request.get_json(silent=True))
        except quick_sale_jobs.SaleConflict as exc:
            return jsonify(status="error", message=str(exc)), 409
        except ValueError as exc:
            return jsonify(status="error", message=str(exc)), 400
        return jsonify(status="success", job=job), 202
    response = jsonify(status="success", accounts=quick_sale_jobs.accounts(), jobs=quick_sale_jobs.jobs())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/fetch_gamble_data", methods=["GET"])
def fetch_gamble_data():
    try:
        # Fetch table data
        rows = get_from_db(
            "SELECT hour, wins, losses FROM gamble_winrate ORDER BY hour"
        )

        # Extract columns as lists
        win_data = [row["wins"] for row in rows]
        lose_data = [row["losses"] for row in rows]

        # Return Data
        return jsonify(
            {"status": "success", "win_data": win_data, "lose_data": lose_data}
        )

    except Exception as e:
        print(f"Error fetching gamble data: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "An error occurred while fetching gamble data",
            }
        ), 500


@app.route("/api/fetch_cowoncy_data", methods=["GET"])
def fetch_cowoncy_data():
    try:
        rows = get_from_db(
            "SELECT user_id, hour, earnings FROM cowoncy_earnings ORDER BY hour"
        )
        user_data = {}
        for row in rows:
            user_id = row["user_id"]
            hour = row["hour"]
            earnings = row["earnings"]

            if user_id not in user_data:
                # Create dummy data
                user_data[user_id] = {i: 0 for i in range(24)}
            # populate
            user_data[user_id][hour] = earnings

        # Base data
        base_data = {"labels": [f"Hour {i}" for i in range(24)], "datasets": []}

        for user_id, hourly_data in user_data.items():
            color_hue = random.randint(0, 360)
            dataset = {
                "label": user_id,
                "data": [hourly_data[i] for i in range(24)],
                "borderColor": f"hsl({color_hue}, 100%, 50%)",
                "backgroundColor": f"hsl({color_hue}, 100%, 70%)",
                "fill": True,
                "tension": 0.4,
                "pointRadius": 0,
            }
            base_data["datasets"].append(dataset)

        rows = get_from_db("SELECT cowoncy, captchas FROM user_stats")
        total_cowoncy = sum(row["cowoncy"] for row in rows)
        # I understand this area is for cowoncy, but accessing thro here since lazy lol.
        total_captchas = sum(row["captchas"] for row in rows)

        return jsonify(
            {
                "status": "success",
                "data": base_data,
                "total_cash": total_cowoncy,
                "total_captchas": total_captchas,
            }
        ), 200

    except Exception as e:
        print(f"Error fetching cowoncy data: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "An error occurred while fetching cowoncy data",
            }
        ), 500


@app.route("/api/fetch_cmd_data", methods=["GET"])
def fetch_cmd_data():
    try:
        rows = get_from_db("SELECT * FROM commands")

        filtered_rows = [row for row in rows if row["count"] != 0]

        command_names = [row["name"] for row in filtered_rows]
        count = [row["count"] for row in filtered_rows]

        for idx, item in enumerate(count):
            if item == 0:
                command_names.pop(idx)
                count.pop(idx)

        # Return Data
        return jsonify(
            {"status": "success", "command_names": command_names, "count": count}
        )

    except Exception as e:
        print(f"Error fetching command data: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "An error occurred while fetching command data",
            }
        ), 500


@app.route("/api/fetch_weekly_runtime", methods=["GET"])
def fetch_weekly_runtime():
    try:
        # Fetch json data (self heals if the file is missing/corrupted)
        data_dict = load_weekly_runtime("utils/data/weekly_runtime.json")

        runtime_data = [
            (val[1] - val[0]) / 60
            for val in data_dict.values()
            if isinstance(val, list)
        ]

        cur_hour = get_weekday()

        # Return Data
        return jsonify(
            {
                "status": "success",
                "runtime_data": runtime_data,
                "current_uptime": data_dict[cur_hour],
            }
        )

    except Exception as e:
        print(f"Error fetching weekly runtime: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "An error occurred while fetching weekly runtime",
            }
        ), 500


def web_start(port, should_host, ver, paswd):
    # Set global variables with respective values
    global version
    version = ver
    # Start the webserver
    flask_log = logging.getLogger("werkzeug")
    flask_log.disabled = True
    cli = sys.modules["flask.cli"]
    setattr(cli, "show_server_banner", lambda *x: None)
    app.run(
        debug=False,
        use_reloader=False,
        port=port,
        host="127.0.0.1",
    )


def website_append(content):
    global website_logs
    website_logs.append(content)

    if len(website_logs) > 300:
        website_logs.pop(0)
