"""Afrihost Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_COOKIES, CONF_SELECTED_PRODUCTS, DOMAIN
from .coordinator import AfrihostCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


def _selected_products(entry: ConfigEntry) -> list[str]:
    """Return the active product selection, preferring options over initial data."""
    return (
        entry.options.get(CONF_SELECTED_PRODUCTS)
        or entry.data.get(CONF_SELECTED_PRODUCTS, [])
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from pyafrihostapi.client import AfrihostClient, LoginError

    client = AfrihostClient(entry.data["username"], entry.data["password"])

    cookies = entry.data.get(CONF_COOKIES, {})
    if cookies:
        client.set_cookies(cookies)

    valid = await hass.async_add_executor_job(client.verify_session)
    if not valid:
        _LOGGER.debug("Stored session expired — attempting fresh login for %s", entry.data["username"])
        try:
            await hass.async_add_executor_job(client.login)
        except LoginError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except Exception as exc:
            raise ConfigEntryNotReady(f"Cannot connect to Afrihost: {exc}") from exc

        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_COOKIES: client.get_cookies()},
        )

    coordinator = AfrihostCoordinator(hass, client, _selected_products(entry))

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        raise ConfigEntryNotReady(f"Initial data fetch failed: {exc}") from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False


async def _async_reload_on_options_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
