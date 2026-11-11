"""Money calculations and stable whole-scene scanning; no camera dependencies."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path

COLORS = ("Pink", "Blue", "Green", "Yellow")
CENT = Decimal("0.01")


def decimal(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money/rate: {value}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Money and rates must be finite and nonnegative")
    return result


def money(value):
    return decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(config["plate_prices"]) != set(COLORS):
        raise ValueError(f"plate_prices must contain exactly {COLORS}")
    for price in config["plate_prices"].values():
        money(price)
    for key in ("service_charge_percent", "vat_percent", "discount_amount"):
        decimal(config[key])
    if config["vat_mode"] not in ("inclusive", "exclusive"):
        raise ValueError("vat_mode must be inclusive or exclusive")
    if not 0 < config["presence_confidence"] <= config["billing_confidence"] <= 1:
        raise ValueError("Require 0 < presence_confidence <= billing_confidence <= 1")
    if type(config["stable_frames"]) is not int or config["stable_frames"] < 1:
        raise ValueError("stable_frames must be a positive integer")
    return config


class Bill:
    def __init__(self, config):
        self.config = config
        self.plates = []
        self.finalized = False

    def add(self, color):
        if self.finalized:
            raise ValueError("Start a new bill before adding plates")
        if color not in self.config["plate_prices"]:
            raise ValueError(f"Unknown color: {color}")
        self.plates.append(color)

    def undo(self):
        if self.finalized:
            raise ValueError("Finalized bills cannot be edited")
        return self.plates.pop() if self.plates else None

    def replace_counts(self, counts):
        """Capture a complete scene, replacing rather than accumulating plates."""
        if self.finalized:
            raise ValueError("Start a new bill before capturing plates")
        if set(counts) - set(COLORS):
            raise ValueError("Unknown plate color")
        if any(type(n) is not int or n < 0 for n in counts.values()):
            raise ValueError("Plate counts must be nonnegative integers")
        self.plates = [color for color in COLORS for _ in range(counts.get(color, 0))]

    def receipt(self):
        counts = Counter(self.plates)
        lines = [dict(color=c, quantity=counts[c],
                      unit_price=str(money(self.config["plate_prices"][c])),
                      amount=str(money(self.config["plate_prices"][c]) * counts[c]))
                 for c in COLORS if counts[c]]
        subtotal = sum((Decimal(line["amount"]) for line in lines), Decimal("0.00"))
        discount = min(money(self.config["discount_amount"]), subtotal)
        net = subtotal - discount
        service = money(net * decimal(self.config["service_charge_percent"]) / 100)
        base = net + service if self.config["vat_on_service_charge"] else net
        rate = decimal(self.config["vat_percent"]) / 100
        if self.config["vat_mode"] == "inclusive":
            vat = money(base * rate / (1 + rate))
            total = net + service
        else:
            vat = money(base * rate)
            total = net + service + vat
        return dict(currency=self.config["currency"], plates=len(self.plates), lines=lines,
                    subtotal=str(subtotal), discount=str(discount), service_charge=str(service),
                    vat=str(vat), total=str(total), vat_mode=self.config["vat_mode"],
                    service_charge_percent=str(self.config["service_charge_percent"]),
                    vat_percent=str(self.config["vat_percent"]),
                    vat_on_service_charge=self.config["vat_on_service_charge"])


@dataclass(frozen=True)
class Detection:
    color: str
    confidence: float


class SceneScanner:
    """A snapshot becomes ready only while the current color counts stay stable."""
    def __init__(self, config):
        self.config = config
        self.candidate = None
        self.streak = 0
        self.ready_counts = None
        self.status = "Show all plates together"

    def update(self, detections):
        self.ready_counts = None
        visible = [d for d in detections if d.confidence >= self.config["presence_confidence"]]
        if not visible:
            self.candidate, self.streak = None, 0
            self.status = "No plates detected"
            return None
        if any(d.color not in COLORS or d.confidence < self.config["billing_confidence"] for d in visible):
            self.candidate, self.streak = None, 0
            self.status = "Uncertain plate: adjust stack or lighting"
            return None
        counts = Counter(d.color for d in visible)
        candidate = tuple(counts[color] for color in COLORS)
        self.streak = min(self.streak + 1, self.config["stable_frames"]) if self.candidate == candidate else 1
        self.candidate = candidate
        self.status = f"Hold all plates still: {self.streak}/{self.config['stable_frames']}"
        if self.streak >= self.config["stable_frames"]:
            self.ready_counts = dict(zip(COLORS, candidate))
            self.status = "Ready: capture all plates (c)"
            return self.ready_counts.copy()
        return None
