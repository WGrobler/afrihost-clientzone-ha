"""DataUpdateCoordinator for the Afrihost integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)


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
            for p in self.client.mobile.raw().get("data", []):
                pid = str(p["id"])
                if pid in sim_ids:
                    wallet: dict = {}
                    try:
                        wallet = self.client.mobile.wallet_balances(p).get("data", {})
                    except Exception:
                        _LOGGER.debug("Could not fetch wallet for mobile_sim:%s", pid)
                    data[f"mobile_sim:{pid}"] = {**p, "_wallet": wallet}

        if voip_ids:
            for p in self.client.voip.raw().get("client_solutions", []):
                pid = str(p["id"])
                if pid in voip_ids:
                    data[f"voip:{pid}"] = p

        if hosting_ids:
            hosting = self.client.hosting.raw()
            usage = hosting.get("usage_stats", {})
            for p in hosting.get("hosting_products", []):
                pid = str(p.get("id", ""))
                if pid in hosting_ids:
                    data[f"hosting:{pid}"] = {**p, "_usage_stats": usage}

        return data
