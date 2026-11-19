"""
Loads message JSON files from discord/embeds/ and fills in {placeholders}.

Each file is a Discord message: {"content": "...", "embeds": [ {embed}, ... ]}, so it can be
pasted from an embed builder. Code supplies placeholders as a dict ('{winner}' -> text);
any embed can also use these without code:
    {channel:casino}      -> <#casino channel id>
    {setting:chip_value}  -> any key from config.yml's `bot` section
Unknown placeholders stay literal; tests/test_embeds.py catches them.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import nextcord

from modules.game_ui import safe_send

EMBEDS_DIR = Path(__file__).resolve().parent.parent / "embeds"
_GENERIC = re.compile(r"\{(channel|setting):([\w\-]+)\}")


def _resolve_generic(match):
    from modules import helpers  # lazy: helpers reads config.yml on import
    kind, key = match.groups()
    if kind == "channel":
        value = helpers.CASINO_CHANNEL_ID if key == "casino" else None
        value = f"<#{value}>" if value else None
    else:
        value = helpers.config.get(key)
    return match.group(0) if value is None else str(value)


def member_replacements(member, name: str = "user") -> Dict[str, str]:
    """Placeholders for one member: {name} mention, {name_name} display name, {name_id}."""
    return {
        f"{{{name}}}": member.mention,
        f"{{{name}_name}}": member.display_name,
        f"{{{name}_id}}": str(member.id),
    }


class EmbedProcessor:
    @staticmethod
    def replace_placeholders(text: str, replacements: Dict[str, str]) -> str:
        if not isinstance(text, str):
            return text
        for placeholder, replacement in replacements.items():
            text = text.replace(placeholder, str(replacement))
        return _GENERIC.sub(_resolve_generic, text)

    @staticmethod
    def process_embed_data(embed_data: Dict[str, Any], replacements: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Deep copy of the message data with placeholders replaced in every string."""
        if not embed_data:
            return None

        def walk(value):
            if isinstance(value, str):
                return EmbedProcessor.replace_placeholders(value, replacements)
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            if isinstance(value, list):
                return [walk(v) for v in value]
            return value

        return walk(embed_data)

    @staticmethod
    def load_embed_data(filename: str, embeds_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Read embeds/<filename>[.json] fresh each time, so text edits apply without a restart.
        Raises if the file is missing or invalid: a broken embed is a deploy bug, not something to hide."""
        if not filename.endswith(".json"):
            filename += ".json"
        with open((embeds_dir or EMBEDS_DIR) / filename, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def to_message_kwargs(data: Dict[str, Any]) -> Dict[str, Any]:
        """{'content', 'embeds'} ready for send / edit / interaction.response.edit_message."""
        embeds = []
        for raw in data.get("embeds", []):
            embed = nextcord.Embed.from_dict({k: v for k, v in raw.items() if k not in ("id", "type")})
            if not embed.footer:
                embed.set_footer(text=datetime.now().strftime("%m/%d/%Y %H:%M:%S"))
            embeds.append(embed)
        # None (not '') so an edit clears an earlier content such as a ping
        return {"content": data.get("content") or None, "embeds": embeds}


def render_embed(filename: str, replacements: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Load, fill in and convert one embed file into message kwargs: channel.send(**render_embed(...))."""
    data = EmbedProcessor.process_embed_data(EmbedProcessor.load_embed_data(filename), replacements or {})
    return EmbedProcessor.to_message_kwargs(data)


async def send_processed_embed(destination, filename: str, replacements: Optional[Dict[str, str]] = None, **kw):
    """Load, fill in and send in one call. Returns the message, or None if the send failed."""
    return await safe_send(destination, **render_embed(filename, replacements), **kw)
