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
from threading import Thread

import requests

import utils.system as syst
from utils.errors import suppress_and_log, suppress_and_log_block
from utils.loader import global_settings_dict
from utils import account_setup, bot_control


def fetch_json(url, description="data"):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        syst.system.print_box(f"Failed to fetch {description}: {e}", "bold red")
        return {}


@suppress_and_log("Run Bot")
def run_bot(token, channel_id, global_settings_dict, token_len, startup_battles=None):
    from core.client import MyClient

    logging.getLogger("discord.client").setLevel(logging.ERROR)

    with suppress_and_log_block("Client Run"):
        client = MyClient(token, channel_id, global_settings_dict, token_len)
        client.startup_battles = startup_battles
        client.run(token, log_level=logging.ERROR)


def run_bots(tokens_and_channels):
    from core.startup_battles import StartupBattles

    threads = []
    account_ids = {token: account_setup.account_id_from_token(token) for token, _ in tokens_and_channels}
    players = tuple(dict.fromkeys(
        account_id for account_id in account_ids.values()
        if account_id and bot_control.get_account_overrides(account_id).get("startupFriendlyBattles") is True
    ))
    startup_battles = StartupBattles(players) if len(players) == 2 else None

    with suppress_and_log_block("Run Bot starter loop"):
        for token, channel_id in tokens_and_channels:
            thread = Thread(
                target=run_bot,
                args=(
                    token,
                    channel_id,
                    global_settings_dict,
                    len(tokens_and_channels),
                    startup_battles if account_ids[token] in players else None,
                ),
            )
            thread.start()
            threads.append(thread)

    for thread in threads:
        thread.join()
