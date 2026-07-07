from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_KNOWN_ENGINES = ("postgres", "oracle", "questdb")
_REQUIRED_FIELDS = ("engine", "dsn", "credential_ref", "tier")


class RegistryError(Exception):
    """Registry file is missing, malformed, or fails schema validation."""


class UnknownEndpointError(Exception):
    """resolve() found no endpoint for the given name — a first-class
    outcome, not a bare KeyError, so callers can reply "unknown host"
    rather than crashing."""


class CredentialRefError(Exception):
    """An endpoint's credential_ref names an env var that isn't set."""


@dataclass(frozen=True)
class Endpoint:
    key: str
    engine: str
    dsn: str
    credential_ref: str
    tier: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def resolve_credential(self, env: dict | None = None) -> str:
        """Look up the actual secret value at call time. The YAML only
        ever stores credential_ref (an env var name) — never a secret —
        so this is the one place a real value comes into existence."""
        env = env if env is not None else os.environ
        value = env.get(self.credential_ref)
        if not value:
            raise CredentialRefError(
                f"credential ref {self.credential_ref!r} for endpoint "
                f"{self.key!r} is not set in the environment"
            )
        return value


@dataclass(frozen=True)
class EndpointRegistry:
    endpoints: dict[str, Endpoint]
    aliases: dict[str, str] = field(default_factory=dict)

    def resolve(self, name: str) -> Endpoint:
        if name in self.endpoints:
            return self.endpoints[name]
        key = self.aliases.get(name)
        if key is not None:
            return self.endpoints[key]
        raise UnknownEndpointError(f"no registry entry for {name!r}")


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of PyYAML's
    default of silently keeping the last one — a duplicated endpoint key
    must fail loudly, not overwrite an entry."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise RegistryError(f"duplicate endpoint key in registry file: {key!r}")
            seen.add(key)
        return super().construct_mapping(node, deep)


def load_registry(path: Path) -> EndpointRegistry:
    if not path.exists():
        raise RegistryError(f"registry file not found: {path}")

    raw = yaml.load(path.read_text(), Loader=_UniqueKeyLoader) or {}
    if not isinstance(raw, dict):
        raise RegistryError(f"registry file must contain a YAML mapping: {path}")

    endpoints: dict[str, Endpoint] = {}

    for key, spec in raw.items():
        if not isinstance(spec, dict):
            raise RegistryError(f"endpoint {key!r} must be a YAML mapping")

        missing = [f for f in _REQUIRED_FIELDS if f not in spec]
        if missing:
            raise RegistryError(
                f"endpoint {key!r} is missing required field(s): {', '.join(missing)}"
            )

        engine = spec["engine"]
        if engine not in _KNOWN_ENGINES:
            raise RegistryError(
                f"endpoint {key!r} has unknown engine {engine!r}; "
                f"must be one of {_KNOWN_ENGINES}"
            )

        endpoints[key] = Endpoint(
            key=key,
            engine=engine,
            dsn=spec["dsn"],
            credential_ref=spec["credential_ref"],
            tier=spec["tier"],
            aliases=tuple(spec.get("aliases") or ()),
        )

    aliases: dict[str, str] = {}
    for key, endpoint in endpoints.items():
        for alias in endpoint.aliases:
            aliases[alias] = key

    return EndpointRegistry(endpoints=endpoints, aliases=aliases)
