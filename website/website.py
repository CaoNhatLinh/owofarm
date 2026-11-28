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
from collections import deque
from hashlib import sha256
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, make_response, render_template, request, url_for

from utils.runtime_handler import load_weekly_runtime, session_uptime_seconds
from utils import bot_control
from utils import quick_sale_jobs
from utils import rare_catches
from utils import gamble_session
from utils import account_setup

app = Flask(__name__)
website_logs = deque(maxlen=300)
_website_logs_lock = Lock()
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


@app.template_global()
def asset_url(filename):
    digest = sha256((Path(app.static_folder) / filename).read_bytes()).hexdigest()[:12]
    return url_for("static", filename=filename, v=digest)


@app.route("/")
def home():
    response = make_response(render_template(
        "index.html", version=version,
        weapon_sale_ranks=quick_sale_jobs.WEAPON_RANKS,
        animal_sale_ranks=quick_sale_jobs.ANIMAL_RANKS,
    ))
    response.cache_control.no_store = True
    return response


@app.route("/api/console", methods=["GET"])
def get_console_logs():
    with _website_logs_lock:
        log_string = "\n".join(website_logs)
    return Response(log_string, mimetype="text/plain", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@app.route("/api/bot", methods=["GET", "POST"])
def control_bot():
    try:
        account_id = requested_account()
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400
    except OSError:
        return jsonify(status="error", message="Không đọc được danh sách tài khoản."), 500
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("action") not in ("start", "stop"):
            return jsonify(status="error", message="Action must be start or stop"), 400
        bot_control.set_running(data["action"] == "start", account_id)
    response = jsonify(status="success", running=bot_control.is_running(account_id),
                       allRunning=bot_control.is_running(),
                       resumeRequest=bot_control.get_resume_generation(account_id),
                       settings=bot_control.get_settings(account_id), accounts=bot_control.get_runtimes(),
                       overrides=bot_control.get_account_overrides(account_id) if account_id else {})
    response.headers["Cache-Control"] = "no-store"
    return response


def requested_account():
    account_id = request.args.get("accountId")
    if account_id is not None and not any(
        account["accountId"] == account_id for account in account_setup.list_accounts()
    ):
        raise ValueError("Tài khoản này không có trong cấu hình.")
    return account_id


@app.route("/api/settings", methods=["GET", "PATCH", "DELETE"])
def dashboard_settings():
    try:
        account_id = requested_account()
        if request.method == "PATCH":
            values = bot_control.validate_settings(request.get_json(silent=True))
            requested_channel = values.get("channelId", "")
            if requested_channel and requested_channel != bot_control.get_settings(account_id)["channelId"]:
                if account_id is None:
                    bot_control.validate_channel(requested_channel)
                elif bot_control.has_channel_checker(account_id):
                    bot_control.validate_channel(requested_channel, account_id)
            bot_control.update_settings(values, account_id)
        elif request.method == "DELETE":
            if account_id is None:
                raise ValueError("Chọn tài khoản cần dùng lại thiết lập mặc định.")
            bot_control.clear_account_settings(account_id, keep_channel=True)
        response = jsonify(status="success", settings=bot_control.get_settings(account_id),
                           overrides=bot_control.get_account_overrides(account_id) if account_id else {})
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400
    except OSError:
        return jsonify(status="error", message="Không đọc hoặc lưu được cấu hình."), 500
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


@app.route("/api/accounts", methods=["GET", "POST"])
def dashboard_accounts():
    if request.content_length and request.content_length > 4096:
        return jsonify(status="error", message="Dữ liệu quá dài."), 413
    try:
        if request.method == "POST":
            account = account_setup.add(request.get_json(silent=True))
            response = jsonify(status="success", account=account)
            response.status_code = 201
        else:
            response = jsonify(status="success", accounts=account_setup.list_accounts())
        response.headers["Cache-Control"] = "no-store"
        return response
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400
    except OSError:
        return jsonify(status="error", message="Không đọc hoặc lưu được tài khoản."), 500


@app.route("/api/accounts/<account_id>", methods=["GET", "PATCH"])
def dashboard_account(account_id):
    if request.content_length and request.content_length > 4096:
        return jsonify(status="error", message="Dữ liệu quá dài."), 413
    try:
        if request.method == "PATCH":
            account = account_setup.update_account(account_id, request.get_json(silent=True))
        elif request.args.get("reveal") == "1":
            account = account_setup.read_account(account_id, reveal=True)
        else:
            account = next((item for item in account_setup.list_accounts() if item["accountId"] == account_id), None)
            if account is None:
                return jsonify(status="error", message="Không tìm thấy tài khoản."), 404
        response = jsonify(status="success", account=account)
        response.headers["Cache-Control"] = "no-store"
        return response
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400
    except OSError:
        return jsonify(status="error", message="Không đọc hoặc lưu được tài khoản."), 500


@app.route("/api/gamble/simulate", methods=["POST"])
def simulate_coinflip():
    from utils.coinflip_simulation import validate, compare
    from utils.coinflip_history import load
    try:
        data = validate(request.get_json(silent=True))
        accounts = {a["accountId"] for a in account_setup.list_accounts()}
        accounts.update(str(a["accountId"]) for a in bot_control.get_runtimes() if a.get("accountId"))
        if data["accountId"] not in accounts:
            raise ValueError("Chọn tài khoản đã lưu để đọc lịch sử.")
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
            user_id = str(row["user_id"])
            hour = row["hour"]
            earnings = row["earnings"]

            if user_id not in user_data:
                # Create dummy data
                user_data[user_id] = {i: 0 for i in range(24)}
            # populate
            user_data[user_id][hour] = earnings

        # Base data
        base_data = {"labels": [f"Hour {i}" for i in range(24)], "datasets": []}

        account_names = {}
        try:
            account_names.update({
                str(account["accountId"]): account["name"]
                for account in account_setup.list_accounts() if account.get("name")
            })
        except (OSError, ValueError):
            app.logger.warning("Could not read saved account names for the cowoncy chart")
        account_names.update({
            str(account["accountId"]): account["name"]
            for account in bot_control.get_runtimes() if account.get("accountId") and account.get("name")
        })

        for position, (user_id, hourly_data) in enumerate(user_data.items(), 1):
            color_hue = random.randint(0, 360)
            dataset = {
                "accountId": user_id,
                "label": account_names.get(user_id) or f"Tài khoản đã lưu {position}",
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
        weekly = load_weekly_runtime()
        return jsonify(
            {
                "status": "success",
                "runtime_data": [seconds / 60 for seconds in weekly["seconds"]],
                "current_uptime": [0, session_uptime_seconds()],
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
    with _website_logs_lock:
        website_logs.append(content)
