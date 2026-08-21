from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .feature_contract import FEATURE_CONTRACT_VERSION
from .supervised_models import CrossAssetNumpyLogisticStrategy


DEPLOYMENT_MODEL_VERSION = "behavioral-distillation-v2-cross-asset-deploy"


@dataclass(frozen=True)
class DeploymentBundle:
    """Immutable-at-runtime model, metadata and data-derived risk envelope."""

    model: CrossAssetNumpyLogisticStrategy
    model_version: str
    feature_contract_version: str
    training_data_sha256: str
    code_commit: str
    deployment_time: str
    frozen_cutoff: str
    symbols: tuple[str, ...]
    position_scales: Mapping[str, float]
    risk_envelope: Mapping[str, Any]
    symbol_policy: Mapping[str, Mapping[str, Any]]

    def validate(self) -> None:
        if self.model_version != DEPLOYMENT_MODEL_VERSION:
            raise ValueError(f"unexpected deployment model version: {self.model_version}")
        if self.feature_contract_version != FEATURE_CONTRACT_VERSION:
            raise ValueError("deployment feature contract does not match runtime contract")
        if not self.training_data_sha256 or len(self.training_data_sha256) != 64:
            raise ValueError("deployment artifact must contain a SHA256 training-data hash")
        if not self.code_commit:
            raise ValueError("deployment artifact must record the code commit")
        if not self.symbols:
            raise ValueError("deployment artifact contains no symbols")
        if not self.risk_envelope:
            raise ValueError("deployment artifact contains no risk envelope")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "artifact_version": "testnet-deployment-bundle-1",
            "model_version": self.model_version,
            "feature_contract_version": self.feature_contract_version,
            "training_data_sha256": self.training_data_sha256,
            "code_commit": self.code_commit,
            "deployment_time": self.deployment_time,
            "frozen_cutoff": self.frozen_cutoff,
            "symbols": list(self.symbols),
            "position_scales": dict(self.position_scales),
            "risk_envelope": self.risk_envelope,
            "symbol_policy": self.symbol_policy,
            "model": self.model.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DeploymentBundle":
        bundle = cls(
            model=CrossAssetNumpyLogisticStrategy.from_dict(payload.get("model", {})),
            model_version=str(payload.get("model_version", "")),
            feature_contract_version=str(payload.get("feature_contract_version", "")),
            training_data_sha256=str(payload.get("training_data_sha256", "")),
            code_commit=str(payload.get("code_commit", "")),
            deployment_time=str(payload.get("deployment_time", "")),
            frozen_cutoff=str(payload.get("frozen_cutoff", "")),
            symbols=tuple(str(item) for item in payload.get("symbols", [])),
            position_scales={str(key): float(value) for key, value in dict(payload.get("position_scales", {})).items()},
            risk_envelope=dict(payload.get("risk_envelope", {})),
            symbol_policy={str(key): dict(value) for key, value in dict(payload.get("symbol_policy", {})).items()},
        )
        bundle.validate()
        return bundle


def load_deployment_bundle(path: str | Path) -> DeploymentBundle:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return DeploymentBundle.from_dict(payload)


def save_deployment_bundle(bundle: DeploymentBundle, path: str | Path) -> None:
    bundle.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "DEPLOYMENT_MODEL_VERSION",
    "DeploymentBundle",
    "load_deployment_bundle",
    "save_deployment_bundle",
    "sha256_file",
    "utc_now",
]
