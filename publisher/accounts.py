from dataclasses import dataclass, replace
import json
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class AccountProfile:
    profile_id: str
    display_name: str
    debug_port: int = 9222
    guide_seen: bool = False

    def __post_init__(self) -> None:
        if not self.profile_id or not self.profile_id.isascii() or not self.profile_id.isalnum():
            raise ValueError("账号标识无效")
        if not self.display_name.strip():
            raise ValueError("账号名称不能为空")
        if not 1024 <= self.debug_port <= 65535:
            raise ValueError("账号调试端口无效")

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "debug_port": self.debug_port,
            "guide_seen": self.guide_seen,
        }

    @classmethod
    def from_dict(cls, value: object) -> "AccountProfile":
        if not isinstance(value, dict):
            raise ValueError("账号信息格式无效")
        return cls(
            profile_id=str(value["profile_id"]),
            display_name=str(value["display_name"]),
            debug_port=int(value.get("debug_port", 9222)),
            guide_seen=bool(value.get("guide_seen", False)),
        )


class AccountRegistry:
    LEGACY_ID = "legacy"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _path(self) -> Path:
        return self.data_dir / "accounts.json"

    def profiles(self) -> tuple[AccountProfile, ...]:
        profiles, _active_id = self._load()
        return tuple(profiles)

    def active(self) -> AccountProfile:
        profiles, active_id = self._load()
        return self._find(profiles, active_id)

    def add(self, display_name: str) -> AccountProfile:
        profiles, _active_id = self._load()
        normalized_name = self._normalized_name(display_name)
        self._require_unique_name(profiles, normalized_name)
        profile = AccountProfile(
            uuid4().hex,
            normalized_name,
            debug_port=self._next_debug_port(profiles),
        )
        self._save([*profiles, profile], profile.profile_id)
        return profile

    def rename(self, profile_id: str, display_name: str) -> AccountProfile:
        profiles, active_id = self._load()
        current = self._find(profiles, profile_id)
        normalized_name = self._normalized_name(display_name)
        self._require_unique_name(profiles, normalized_name, excluding=profile_id)
        updated = replace(current, display_name=normalized_name)
        self._save(
            [updated if profile.profile_id == profile_id else profile for profile in profiles],
            active_id,
        )
        return updated

    def set_active(self, profile_id: str) -> AccountProfile:
        profiles, _active_id = self._load()
        account = self._find(profiles, profile_id)
        self._save(profiles, account.profile_id)
        return account

    def mark_guide_seen(self, profile_id: str) -> AccountProfile:
        profiles, active_id = self._load()
        current = self._find(profiles, profile_id)
        updated = replace(current, guide_seen=True)
        self._save(
            [updated if profile.profile_id == profile_id else profile for profile in profiles],
            active_id,
        )
        return updated

    def workspace_dir(self, profile_id: str) -> Path:
        self._require_profile(profile_id)
        if profile_id == self.LEGACY_ID:
            return self.data_dir
        return self.data_dir / "accounts" / profile_id / "workspace"

    def edge_profile_dir(self, profile_id: str) -> Path:
        self._require_profile(profile_id)
        if profile_id == self.LEGACY_ID:
            return self.data_dir / "fanqie-edge-profile"
        return self.data_dir / "accounts" / profile_id / "edge-profile"

    def _require_profile(self, profile_id: str) -> None:
        profiles, _active_id = self._load()
        self._find(profiles, profile_id)

    def _load(self) -> tuple[list[AccountProfile], str]:
        if not self._path.exists():
            return [AccountProfile(self.LEGACY_ID, "默认账号")], self.LEGACY_ID
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("账号配置格式无效")
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raise ValueError("账号配置缺少账号列表")
        profiles = [AccountProfile.from_dict(item) for item in raw_profiles]
        if len({profile.profile_id for profile in profiles}) != len(profiles):
            raise ValueError("账号标识重复")
        if len({profile.debug_port for profile in profiles}) != len(profiles):
            raise ValueError("账号调试端口重复")
        active_id = str(payload.get("active_profile_id", self.LEGACY_ID))
        self._find(profiles, active_id)
        return profiles, active_id

    def _save(self, profiles: list[AccountProfile], active_id: str) -> None:
        self._find(profiles, active_id)
        payload = {
            "format_version": 1,
            "active_profile_id": active_id,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        temporary_path = self._path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self._path)

    @staticmethod
    def _find(profiles: list[AccountProfile], profile_id: str) -> AccountProfile:
        for profile in profiles:
            if profile.profile_id == profile_id:
                return profile
        raise KeyError(f"未知账号: {profile_id}")

    @staticmethod
    def _normalized_name(display_name: str) -> str:
        value = display_name.strip()
        if not value:
            raise ValueError("账号名称不能为空")
        return value

    @staticmethod
    def _require_unique_name(
        profiles: list[AccountProfile],
        display_name: str,
        *,
        excluding: str | None = None,
    ) -> None:
        normalized = display_name.casefold()
        if any(
            profile.profile_id != excluding
            and profile.display_name.casefold() == normalized
            for profile in profiles
        ):
            raise ValueError("账号名称重复")

    @staticmethod
    def _next_debug_port(profiles: list[AccountProfile]) -> int:
        used_ports = {profile.debug_port for profile in profiles}
        for port in range(9223, 65536):
            if port not in used_ports:
                return port
        raise RuntimeError("没有可用的账号调试端口")
