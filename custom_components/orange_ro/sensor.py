"""Sensor platform for Orange Romania."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OrangeConfigEntry
from .const import DOMAIN, UNLIMITED
from .coordinator import OrangeDataCoordinator

_LOGGER = logging.getLogger(__name__)

CURRENCY_RON = "RON"


# --------------------------------------------------------------------------- #
# Value parsing helpers
# --------------------------------------------------------------------------- #
def _to_float(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _ms_to_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _iso_to_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        # Handle the "+03" short offset Orange returns, e.g. 2026-07-11T00:00:00+03
        text = re.sub(r"([+-]\d{2})$", r"\1:00", text)
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _iso_to_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _resource_unit(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if low.startswith("minut"):
        return "min"
    if low in ("nelimitat",):
        return None
    return raw  # GB / MB / SMS / etc. pass through


# --------------------------------------------------------------------------- #
# Entity descriptions for the static (per-profile / per-subscriber) sensors
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, kw_only=True)
class OrangeProfileSensorDescription(SensorEntityDescription):
    """Profile-level sensor backed by a value function over profile data."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class OrangeSubscriberSensorDescription(SensorEntityDescription):
    """Line-level sensor backed by a value function over subscriber data."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


PROFILE_SENSORS: tuple[OrangeProfileSensorDescription, ...] = (
    OrangeProfileSensorDescription(
        key="thank_you_points",
        translation_key="thank_you_points",
        icon="mdi:gift",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="points",
        value_fn=lambda p: _to_float(p["customer"].get("otyPoints")),
        attrs_fn=lambda p: {"info": p["customer"].get("otyInfo")},
    ),
    OrangeProfileSensorDescription(
        key="thank_you_value",
        translation_key="thank_you_value",
        icon="mdi:cash-multiple",
        native_unit_of_measurement=CURRENCY_EURO,
        value_fn=lambda p: _to_float(p["customer"].get("otyPointValue")),
    ),
    OrangeProfileSensorDescription(
        key="balance_total",
        translation_key="balance_total",
        icon="mdi:scale-balance",
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: _to_float(p["invoice"].get("totalBalanceAmount")),
        attrs_fn=lambda p: {
            "installments_balance": _to_float(p["invoice"].get("totalBalanceInstallments")),
            "services_balance": _to_float(p["invoice"].get("totalBalanceServices")),
        },
    ),
    OrangeProfileSensorDescription(
        key="last_bill_amount",
        translation_key="last_bill_amount",
        icon="mdi:receipt",
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: _to_float(p["invoice"].get("lastBillIssuedAmount")),
        attrs_fn=lambda p: {"reference": p["invoice"].get("reference")},
    ),
    OrangeProfileSensorDescription(
        key="last_bill_date",
        translation_key="last_bill_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda p: _ms_to_datetime(p["invoice"].get("lastBillIssueDate")),
    ),
    OrangeProfileSensorDescription(
        key="bill_due_date",
        translation_key="bill_due_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda p: _ms_to_datetime(p["invoice"].get("dueDate")),
    ),
    OrangeProfileSensorDescription(
        key="next_bill_date",
        translation_key="next_bill_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda p: _ms_to_datetime(p["invoice"].get("nextBillDate")),
    ),
    OrangeProfileSensorDescription(
        key="installments_count",
        translation_key="installments_count",
        icon="mdi:cellphone-arrow-down",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: len(p.get("installments") or []),
    ),
    OrangeProfileSensorDescription(
        key="invoices",
        translation_key="invoices",
        icon="mdi:file-document-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: len(p.get("transactions") or []),
        attrs_fn=lambda p: {
            "transactions": [
                {
                    "reference": t.get("ref1"),
                    "msisdn": t.get("ref2"),
                    "amount": _to_float(t.get("value")),
                    "balance": _to_float(t.get("balance")),
                    "date": _ms_to_datetime(t.get("transDate")).isoformat()
                    if _ms_to_datetime(t.get("transDate"))
                    else None,
                    "code": t.get("code"),
                }
                for t in (p.get("transactions") or [])[:24]
            ]
        },
    ),
)


def _earliest_resource_validity(sub: dict[str, Any]) -> datetime | None:
    resources = (sub.get("cronos") or {}).get("resources") or []
    dts = [
        dt
        for r in resources
        if (dt := _iso_to_datetime(r.get("validUntil"))) is not None
    ]
    return min(dts) if dts else None


def _extra_cost(sub: dict[str, Any]) -> float | None:
    costs = (sub.get("cronos") or {}).get("cost") or []
    total = 0.0
    found = False
    for c in costs:
        val = _to_float(c.get("value"))
        if val is not None:
            total += val
            found = True
    return round(total, 2) if found else None


SUBSCRIBER_SENSORS: tuple[OrangeSubscriberSensorDescription, ...] = (
    OrangeSubscriberSensorDescription(
        key="subscription",
        translation_key="subscription",
        icon="mdi:sim",
        value_fn=lambda s: (s["detail"].get("subscription") or {}).get("subscriptionName")
        or s["summary"].get("subscriptionName"),
        attrs_fn=lambda s: {
            "code": (s["detail"].get("subscription") or {}).get("subscriptionCode"),
            "tags": (s["detail"].get("subscription") or {}).get("tags"),
            "type": s["summary"].get("subscriberTypeDisplayName"),
        },
    ),
    OrangeSubscriberSensorDescription(
        key="monthly_fee",
        translation_key="monthly_fee",
        icon="mdi:cash",
        native_unit_of_measurement=CURRENCY_EURO,
        value_fn=lambda s: (
            v / 100
            if (v := (s["detail"].get("subscription") or {}).get("optionAmountEurWithVat"))
            is not None
            else None
        ),
    ),
    OrangeSubscriberSensorDescription(
        key="line_status",
        translation_key="line_status",
        icon="mdi:cellphone-check",
        value_fn=lambda s: s["detail"].get("msisdnStatus") or s["summary"].get("status"),
    ),
    OrangeSubscriberSensorDescription(
        key="extra_cost",
        translation_key="extra_cost",
        icon="mdi:cash-plus",
        native_unit_of_measurement="EURc",
        value_fn=_extra_cost,
    ),
    OrangeSubscriberSensorDescription(
        key="resources_valid_until",
        translation_key="resources_valid_until",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_earliest_resource_validity,
        attrs_fn=lambda s: {
            "resources": (s.get("cronos") or {}).get("resources"),
        },
    ),
    OrangeSubscriberSensorDescription(
        key="upgrade_eligible_date",
        translation_key="upgrade_eligible_date",
        device_class=SensorDeviceClass.DATE,
        icon="mdi:cellphone-arrow-down-variant",
        value_fn=lambda s: _iso_to_date(s["detail"].get("fidelityExpirationDate")),
    ),
    OrangeSubscriberSensorDescription(
        key="activation_date",
        translation_key="activation_date",
        device_class=SensorDeviceClass.DATE,
        icon="mdi:calendar-start",
        value_fn=lambda s: _iso_to_date(s["detail"].get("switchOnDate")),
    ),
    OrangeSubscriberSensorDescription(
        key="phone_credit",
        translation_key="phone_credit",
        icon="mdi:credit-card-clock",
        value_fn=lambda s: s["extra"].get("orangePhoneCredit"),
    ),
)


# --------------------------------------------------------------------------- #
# Platform setup
# --------------------------------------------------------------------------- #
async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrangeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Orange sensors from the coordinator snapshot."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    profiles: dict[str, Any] = (coordinator.data or {}).get("profiles", {})
    for profile_id, profile in profiles.items():
        for desc in PROFILE_SENSORS:
            entities.append(OrangeProfileSensor(coordinator, profile_id, desc))

        for sub_id, sub in profile.get("subscribers", {}).items():
            for sdesc in SUBSCRIBER_SENSORS:
                entities.append(
                    OrangeSubscriberSensor(coordinator, profile_id, sub_id, sdesc)
                )

            # One numeric sensor per *metered* Cronos resource. Unlimited
            # resources stay visible as attributes on "resources_valid_until".
            for res in (sub.get("cronos") or {}).get("resources") or []:
                if str(res.get("total")) == UNLIMITED:
                    continue
                name = res.get("name")
                if not name:
                    continue
                entities.append(
                    OrangeResourceSensor(coordinator, profile_id, sub_id, name)
                )

    async_add_entities(entities)


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
def _profile_device(profile: dict[str, Any], profile_id: str) -> DeviceInfo:
    info = profile.get("info", {})
    name = info.get("name") or f"Profile {profile_id}"
    return DeviceInfo(
        identifiers={(DOMAIN, f"profile_{profile_id}")},
        manufacturer="Orange Romania",
        name=f"Orange {name}",
        model="Account profile",
    )


def _subscriber_device(sub: dict[str, Any], profile_id: str, sub_id: str) -> DeviceInfo:
    msisdn = sub.get("summary", {}).get("msisdn") or sub_id
    sub_name = (sub.get("detail", {}).get("subscription") or {}).get("subscriptionName")
    return DeviceInfo(
        identifiers={(DOMAIN, f"sub_{sub_id}")},
        via_device=(DOMAIN, f"profile_{profile_id}"),
        manufacturer="Orange Romania",
        name=f"Orange {msisdn}",
        model=sub_name or "Mobile line",
    )


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
class OrangeProfileSensor(CoordinatorEntity[OrangeDataCoordinator], SensorEntity):
    """A profile-level sensor."""

    _attr_has_entity_name = True
    entity_description: OrangeProfileSensorDescription

    def __init__(
        self,
        coordinator: OrangeDataCoordinator,
        profile_id: str,
        description: OrangeProfileSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._profile_id = profile_id
        self.entity_description = description
        self._attr_unique_id = f"{profile_id}_{description.key}"
        self._attr_device_info = _profile_device(self._profile(), profile_id)

    def _profile(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("profiles", {}).get(self._profile_id, {})

    @property
    def native_value(self) -> Any:
        profile = self._profile()
        if not profile:
            return None
        try:
            return self.entity_description.value_fn(profile)
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        profile = self._profile()
        if not profile:
            return None
        try:
            return {k: v for k, v in self.entity_description.attrs_fn(profile).items()}
        except (KeyError, TypeError, ValueError):
            return None


class OrangeSubscriberSensor(CoordinatorEntity[OrangeDataCoordinator], SensorEntity):
    """A line-level sensor."""

    _attr_has_entity_name = True
    entity_description: OrangeSubscriberSensorDescription

    def __init__(
        self,
        coordinator: OrangeDataCoordinator,
        profile_id: str,
        sub_id: str,
        description: OrangeSubscriberSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._profile_id = profile_id
        self._sub_id = sub_id
        self.entity_description = description
        self._attr_unique_id = f"{sub_id}_{description.key}"
        self._attr_device_info = _subscriber_device(self._sub(), profile_id, sub_id)

    def _sub(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("profiles", {})
            .get(self._profile_id, {})
            .get("subscribers", {})
            .get(self._sub_id, {})
        )

    @property
    def native_value(self) -> Any:
        sub = self._sub()
        if not sub:
            return None
        try:
            return self.entity_description.value_fn(sub)
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        sub = self._sub()
        if not sub:
            return None
        try:
            return {k: v for k, v in self.entity_description.attrs_fn(sub).items()}
        except (KeyError, TypeError, ValueError):
            return None


class OrangeResourceSensor(CoordinatorEntity[OrangeDataCoordinator], SensorEntity):
    """A metered Cronos resource (data / minutes / SMS remaining)."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: OrangeDataCoordinator,
        profile_id: str,
        sub_id: str,
        resource_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._profile_id = profile_id
        self._sub_id = sub_id
        self._resource_name = resource_name
        self._attr_unique_id = f"{sub_id}_res_{_slug(resource_name)}"
        self._attr_name = resource_name
        self._attr_icon = "mdi:gauge"
        self._attr_device_info = _subscriber_device(self._sub(), profile_id, sub_id)
        self._attr_native_unit_of_measurement = _resource_unit(self._resource().get("resourceUnit"))

    def _sub(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("profiles", {})
            .get(self._profile_id, {})
            .get("subscribers", {})
            .get(self._sub_id, {})
        )

    def _resource(self) -> dict[str, Any]:
        for res in (self._sub().get("cronos") or {}).get("resources") or []:
            if res.get("name") == self._resource_name:
                return res
        return {}

    @property
    def native_value(self) -> float | None:
        return _to_float(self._resource().get("remaining"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        res = self._resource()
        return {
            "consumed": _to_float(res.get("consumed")),
            "total": _to_float(res.get("total")),
            "category": res.get("marketingCategory"),
            "valid_until": res.get("validUntil"),
        }
