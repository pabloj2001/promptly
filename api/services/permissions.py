"""Compile a per-project permissions profile (09) into Claude CLI arguments.

Promptly never writes `.claude/settings.json` into the user's repo; instead it passes an
ephemeral settings object via ``--settings`` per call, plus ``--permission-mode`` and
``--add-dir``. `permissions.json` (read by StorageService) stays the single user-editable
source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..models import PermissionProfile, PermissionsConfig


@dataclass
class CliPermissions:
    settings_json: str           # value for --settings
    permission_mode: str         # value for --permission-mode
    add_dirs: list[str] = field(default_factory=list)  # values for --add-dir


def build_cli_permissions(
    config: PermissionsConfig, profile_name: str, *, repo_root: str
) -> CliPermissions:
    """Translate the named profile (``generation`` | ``execution``) into CLI args.

    The repo root is always granted (so reads span the whole repo) along with any
    user-configured ``additionalReadDirs``.
    """
    profile: PermissionProfile = getattr(config, profile_name)
    add_dirs = [repo_root, *config.additional_read_dirs]
    settings = {
        "permissions": {
            "allow": list(profile.allow),
            "deny": list(profile.deny),
            "additionalDirectories": add_dirs,
        },
        "defaultMode": profile.permission_mode,
    }
    return CliPermissions(
        settings_json=json.dumps(settings),
        permission_mode=profile.permission_mode,
        add_dirs=add_dirs,
    )
