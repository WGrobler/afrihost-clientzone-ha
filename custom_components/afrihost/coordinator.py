"""DataUpdateCoordinator for the Afrihost integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)


def _normalize_airmobile_wallet(resp: dict) -> dict:
    """Convert /balances/summary response to the internal wallet dict.

    Input:  {"balances": [{"slug": "airtime", "amount": 2000, ...},
                          {"slug": "data",    "amount": 6139220654, ...}]}

    Output uses the same keys as the voice wallet so sensors work identically:
      summary_airtime  — airtime in cents, display_amount=0.01 → rands
      _data_remaining_bytes — raw bytes, converted to GB by the sensor
    """
    wallet: dict = {}
    for b in resp.get("balances") or []:
        slug = b.get("slug")
        amount = b.get("amount", 0)
        if slug == "airtime":
            wallet["summary_airtime"] = {
                "balance": amount,
                "airtime_wallet_type": {
                    "display_amount": 0.01,
                    "display_unit": {"symbol": "R", "prefix_symbol": True},
                },
            }
        elif slug == "data":
            wallet["_data_remaining_bytes"] = amount
    return wallet


class AfrihostCoordinator(DataUpdateCoordinator[dict]):
    """Fetch data for every selected product in a single update cycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        client,
        selected_products: list[str],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.client = client
        self.selected_products = selected_products

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except Exception as exc:
            raise UpdateFailed(f"Error fetching Afrihost data: {exc}") from exc

    # ------------------------------------------------------------------
    # Synchronous fetch — runs in the executor
    # ------------------------------------------------------------------

    def _fetch(self) -> dict:
        data: dict = {}

        wireless_ids = {k.split(":")[1] for k in self.selected_products if k.startswith("wireless:")}
        apn_ids      = {k.split(":")[1] for k in self.selected_products if k.startswith("mobile_apn:")}
        sim_ids      = {k.split(":")[1] for k in self.selected_products if k.startswith("mobile_sim:")}
        voip_ids     = {k.split(":")[1] for k in self.selected_products if k.startswith("voip:")}
        device_ids   = {k.split(":")[1] for k in self.selected_products if k.startswith("device:")}
        hosting_ids  = {k.split(":")[1] for k in self.selected_products if k.startswith("hosting:")}

        # One connectivity call covers wireless, APN data, and devices
        if wireless_ids or apn_ids or device_ids:
            conn = self.client.connectivity.raw()
            for p in conn.get("fixed_wireless_products", []):
                pid = str(p["id"])
                if pid in wireless_ids:
                    data[f"wireless:{pid}"] = p
            for p in conn.get("data_products", []):
                pid = str(p["id"])
                if pid in apn_ids:
                    data[f"mobile_apn:{pid}"] = p
            for p in conn.get("device_products", []):
                pid = str(p["id"])
                if pid in device_ids:
                    data[f"device:{pid}"] = p

        if sim_ids:
            from pyafrihostapi.client import _is_airmobile
            for p in self.client.mobile.raw().get("data", []):
                pid = str(p["id"])
                if pid in sim_ids:
                    wallet: dict = {}
                    wallet_source = "airmobile" if _is_airmobile(p) else "voice"
                    try:
                        resp = self.client.mobile.wallet_balances(p)
                        if wallet_source == "airmobile":
                            wallet = _normalize_airmobile_wallet(resp)
                        else:
                            wallet = resp.get("data", {})
                    except Exception:
                        _LOGGER.debug("Could not fetch wallet for mobile_sim:%s", pid)
                    composite_usage: dict = {}
                    if wallet_source != "airmobile":
                        try:
                            comp = self.client.mobile.composite(pid)
                            composite_usage = (
                                comp.get("data", {}).get("data", {}).get("usage", {})
                            )
                        except Exception:
                            _LOGGER.debug("Could not fetch composite for mobile_sim:%s", pid)
                    data[f"mobile_sim:{pid}"] = {
                        **p,
                        "_wallet": wallet,
                        "_wallet_source": wallet_source,
                        "_composite": composite_usage,
                    }

        if voip_ids:
            for p in self.client.voip.raw().get("client_solutions", []):
                pid = str(p["id"])
                if pid in voip_ids:
                    airtime_balances: list = []
                    try:
                        resp = self.client.voip.airtime_balances_live(pid)
                        airtime_balances = resp.get("balances", [])
                    except Exception:
                        _LOGGER.debug("Could not fetch airtime balance for voip:%s", pid)
                    data[f"voip:{pid}"] = {**p, "_airtime": airtime_balances}

        if hosting_ids:
            hosting = self.client.hosting.raw()
            usage = hosting.get("usage_stats", {})
            for p in hosting.get("hosting_products", []):
                pid = str(p.get("id", ""))
                if pid in hosting_ids:
                    data[f"hosting:{pid}"] = {**p, "_usage_stats": usage}

        return data
