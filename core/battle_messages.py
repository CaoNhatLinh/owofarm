import re
from urllib.parse import urlsplit


_TIE = re.compile(r"It's a tie in [1-9]\d* turns!|Battle was too long! It's a tie!")
_AVATAR_USER = re.compile(r"/(?:avatars/|guilds/\d+/users/)(\d+)/")
_DISCORD_CDN = {"cdn.discordapp.com", "media.discordapp.net"}


def _is_scoped(message, *, channel_id, owo_id, after_id):
    return (
        getattr(getattr(message, "channel", None), "id", None) == channel_id
        and getattr(getattr(message, "author", None), "id", None) == owo_id
        and getattr(message, "id", 0) > after_id
    )


def _names(values):
    if isinstance(values, str):
        values = (values,)
    return {value for value in values or () if isinstance(value, str) and value}


def _avatar_user_id(author):
    try:
        url = urlsplit(str(getattr(author, "icon_url", None) or ""))
    except ValueError:
        return None
    if url.hostname in _DISCORD_CDN:
        match = _AVATAR_USER.match(url.path)
        if match:
            return int(match[1])
    return None


def accept_button(message, *, channel_id, owo_id, after_id, receiver_id,
                  sender_names, receiver_names, sender_id=None):
    """Return the enabled native Accept component on the fresh, exact invite."""
    if not _is_scoped(message, channel_id=channel_id, owo_id=owo_id, after_id=after_id):
        return None
    if sender_id == receiver_id or getattr(message, "content", "") != f"<@{receiver_id}>":
        return None
    reference_id = getattr(getattr(message, "reference", None), "message_id", None)
    if reference_id is not None and reference_id != after_id:
        return None

    sender_names, receiver_names = _names(sender_names), _names(receiver_names)
    for embed in getattr(message, "embeds", ()):
        author = getattr(embed, "author", None)
        avatar_user_id = _avatar_user_id(author)
        if avatar_user_id is not None and sender_id is not None and avatar_user_id != sender_id:
            continue
        candidate_names = sender_names
        if avatar_user_id is None or sender_id is None:
            candidate_names = sender_names - receiver_names
        expected_titles = {
            f"{receiver}, {sender} challenges you to a duel!"
            for receiver in receiver_names for sender in candidate_names
        }
        if getattr(author, "name", None) not in expected_titles:
            continue
        if getattr(getattr(embed, "footer", None), "text", None) != "This challenge will expire in 10 minutes":
            continue
        description = getattr(embed, "description", "") or ""
        if "with the bet" in description.casefold():
            continue
        buttons = [
            button
            for row in getattr(message, "components", ())
            for button in getattr(row, "children", ())
            if getattr(button, "custom_id", None) == "battle_accept"
        ]
        if len(buttons) == 1 and getattr(buttons[0], "disabled", True) is False:
            return buttons[0]
    return None


def is_battle_result(message, *, channel_id, owo_id, after_id, sender_names, receiver_names, sender_id=None):
    """Identify a friendly result after the verified invitation was accepted."""
    if not _is_scoped(message, channel_id=channel_id, owo_id=owo_id, after_id=after_id):
        return False

    sender_names, receiver_names = _names(sender_names), _names(receiver_names)
    if not sender_names or not receiver_names:
        return False
    titles = {
        title
        for sender in sender_names for receiver in receiver_names if sender != receiver
        for title in (f"{sender} vs {receiver}", f"{receiver} vs {sender}")
    }
    participant_names = sender_names | receiver_names
    # The original challenge sender can be used as the native result title.
    sender_titles = {f"{name} goes into battle!" for name in sender_names}
    winning_footers = {f"{name} wins!" for name in participant_names}
    for embed in getattr(message, "embeds", ()):
        footer = getattr(getattr(embed, "footer", None), "text", "") or ""
        author = getattr(embed, "author", None)
        title = getattr(author, "name", None)
        avatar_id = _avatar_user_id(author)
        tied = _TIE.fullmatch(footer)
        from_sender = title in sender_titles and (avatar_id is None or sender_id is None or avatar_id == sender_id)
        if (title in titles or from_sender) and (footer in winning_footers or tied):
            return True
    return False
