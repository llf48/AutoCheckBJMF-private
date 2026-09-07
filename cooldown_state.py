"""Small, credential-free account deadlines shared by serialized cloud runs."""
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path


class CooldownStateError(RuntimeError):
    pass


class CooldownState:
    def __init__(self, path=""):
        self.path = Path(path) if path else None
        self.accounts = {}
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("accounts"), dict):
                    raise ValueError("Invalid state schema")
                for key, value in data["accounts"].items():
                    if not re.fullmatch(r"[a-f0-9]{64}", key) or not isinstance(value, dict):
                        raise ValueError("Invalid account record")
                    until = value.get("until")
                    if type(until) not in (int, float) or not math.isfinite(until) or until < 0:
                        raise ValueError("Invalid deadline")
                    self.accounts[key] = {"until": until}
            except (OSError, ValueError, TypeError) as exc:
                raise CooldownStateError("Cannot read account cooldown state; stopped before network access.") from exc

    @staticmethod
    def account_key(student_id, cookie):
        # Stable across account reordering and cookie renewal. Unknown identities
        # use a digest of the cookie, never its plaintext.
        identity = "student:" + student_id if student_id != "unknown" else "cookie:" + cookie
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def deadline(self, key):
        until = self.accounts.get(key, {}).get("until", 0)
        return until if until > time.time() else 0

    def mark(self, key, seconds):
        until = max(self.accounts.get(key, {}).get("until", 0), time.time() + seconds)
        self.accounts[key] = {"until": until}
        self.save()
        return until

    def clear_expired(self, key):
        if key in self.accounts and not self.deadline(key):
            del self.accounts[key]
            self.save()

    def save(self):
        if self.path is None:
            return
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"version": 1, "accounts": self.accounts}, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CooldownStateError("Cannot persist account cooldown state; its in-memory deadline is still active.") from exc


def cooldown_delay_seconds(text, default_minutes=30):
    # Only parse explicit waiting instructions, not the "each visit adds 1
    # minute" penalty that can appear later in the same message.
    durations = []
    unit_seconds = {"小时": 3600, "分钟": 60, "秒": 1}
    patterns = (
        r"(\d+(?:\.\d+)?)\s*(小时|分钟|秒)\s*(?:完全)?后\s*(?:再|才能|才可)?\s*访问",
        r"(?:请|需要|需)?(?:等待|等候)\s*(\d+(?:\.\d+)?)\s*(小时|分钟|秒)",
    )
    for pattern in patterns:
        durations.extend(float(amount) * unit_seconds[unit] for amount, unit in re.findall(pattern, text))
    # Add one minute to an explicit server duration to avoid boundary/rounding
    # retries. Without one, use the configured backoff, not a guessed unlock time.
    return max(durations) + 60 if durations else max(1, int(default_minutes)) * 60
