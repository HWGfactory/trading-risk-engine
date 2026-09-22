"""시장 관행(세율·계약명세·한도) 로더.

값은 config/market_conventions.yaml 한 곳에서만 관리한다.
Windows 기본 인코딩(cp949)과 무관하게 항상 UTF-8로 읽는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "market_conventions.yaml"


@dataclass(frozen=True)
class TaxRule:
    market: str
    securities_tax: Decimal
    rural_special_tax: Decimal

    @property
    def total(self) -> Decimal:
        return self.securities_tax + self.rural_special_tax


@dataclass(frozen=True)
class ContractSpec:
    code: str
    name: str
    multiplier: Decimal
    tick_size: Decimal

    def is_on_tick(self, price: Decimal) -> bool:
        """호가단위 배수인지. tick_size가 0이면 검증하지 않는다."""
        return self.tick_size == 0 or price % self.tick_size == 0


@dataclass(frozen=True)
class RiskLimits:
    max_position_notional: Decimal
    max_gross_exposure: Decimal
    max_loss: Decimal


@dataclass(frozen=True)
class Conventions:
    verified_as_of: str
    tax_source: str
    contract_source: str
    tax_rules: dict[str, TaxRule]
    contracts: dict[str, ContractSpec]
    default_commission_rate: Decimal
    limits: RiskLimits

    def tax_rule(self, market: str) -> TaxRule:
        try:
            return self.tax_rules[market]
        except KeyError:
            raise ValueError(f"거래세 규칙이 없는 시장입니다: {market}") from None

    def contract(self, code: str) -> ContractSpec:
        try:
            return self.contracts[code]
        except KeyError:
            raise ValueError(f"등록되지 않은 계약 코드입니다: {code}") from None


def _d(value: object) -> Decimal:
    return Decimal(str(value))


@lru_cache
def load_conventions(path: str | None = None) -> Conventions:
    config_path = Path(path or os.getenv("TRE_CONVENTIONS_PATH") or DEFAULT_PATH)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    tax = raw["transaction_tax"]
    contracts = raw["contracts"]
    limits = raw["risk_limits"]

    return Conventions(
        verified_as_of=str(raw["verified_as_of"]),
        tax_source=tax["source"],
        contract_source=contracts["source"],
        tax_rules={
            market: TaxRule(market, _d(v["securities_tax"]), _d(v["rural_special_tax"]))
            for market, v in tax["markets"].items()
        },
        contracts={
            code: ContractSpec(code, v["name"], _d(v["multiplier"]), _d(v["tick_size"]))
            for code, v in contracts["items"].items()
        },
        default_commission_rate=_d(raw["default_commission_rate"]),
        limits=RiskLimits(
            max_position_notional=_d(limits["max_position_notional"]),
            max_gross_exposure=_d(limits["max_gross_exposure"]),
            max_loss=_d(limits["max_loss"]),
        ),
    )
