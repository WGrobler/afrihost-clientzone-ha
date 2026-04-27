"""Config flow for the Afrihost integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_COOKIES, CONF_SELECTED_PRODUCTS, DOMAIN

_LOGGER = logging.getLogger(__name__)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required("username"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required("password"): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

_TWOFA_SCHEMA = vol.Schema(
    {
        vol.Required("code"): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.TEXT, autocomplete="one-time-code"
            )
        ),
    }
)


def _gather_products(client) -> dict[str, str]:
    """Return {product_key: display_label} for every product on the account."""
    options: dict[str, str] = {}

    try:
        for p in client.wireless.products():
            key = f"wireless:{p['id']}"
            label = p.get("display_name") or p.get("name") or p["id"]
            options[key] = f"LTE/Wireless: {label}"
    except Exception:
        pass

    try:
        mobile = client.mobile.products()
        for p in mobile.get("mobile_solutions", []):
            key = f"mobile_sim:{p['id']}"
            options[key] = f"Mobile SIM: {p.get('friendlyname') or p['id']}"
        for p in mobile.get("apn_packages", []):
            key = f"mobile_apn:{p['id']}"
            label = p.get("display_name") or p.get("name") or p["id"]
            options[key] = f"Mobile Data: {label}"
    except Exception:
        pass

    try:
        for p in client.voip.products():
            key = f"voip:{p['id']}"
            options[key] = f"VoIP: {p.get('friendlyname') or p.get('uid') or p['id']}"
    except Exception:
        pass

    try:
        for p in client.devices.products():
            key = f"device:{p['id']}"
            label = p.get("description") or (p.get("sub_product_item") or {}).get("name") or p["id"]
            options[key] = f"Device: {label}"
    except Exception:
        pass

    try:
        for p in client.hosting.raw().get("hosting_products", []):
            pid = p.get("id")
            if pid is not None:
                key = f"hosting:{pid}"
                options[key] = f"Hosting: {p.get('name') or p.get('display_name') or pid}"
    except Exception:
        pass

    return options


def _product_select_schema(
    options: dict[str, str], current: list[str]
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_PRODUCTS, default=current): SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in options.items()],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
    )


class AfrihostConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Afrihost config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> AfrihostOptionsFlow:
        return AfrihostOptionsFlow()

    def __init__(self) -> None:
        self._client = None
        self._username: str | None = None
        self._password: str | None = None
        self._product_options: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Step 1 — credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            from pyafrihostapi.client import AfrihostClient, LoginError

            client = AfrihostClient(user_input["username"], user_input["password"])
            try:
                await self.hass.async_add_executor_job(client.login)
                self._client = client
                self._username = user_input["username"]
                self._password = user_input["password"]
                return await self.async_step_products()

            except LoginError as exc:
                if client._pending_2fa:
                    self._client = client
                    self._username = user_input["username"]
                    self._password = user_input["password"]
                    return await self.async_step_twofa()
                _LOGGER.debug("Login error: %s", exc)
                errors["base"] = "invalid_auth"

            except Exception as exc:
                _LOGGER.exception("Unexpected error during login: %s", exc)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=_USER_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 (conditional) — OTP / 2FA
    # ------------------------------------------------------------------

    async def async_step_twofa(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            from pyafrihostapi.client import LoginError

            try:
                await self.hass.async_add_executor_job(
                    self._client.submit_2fa, user_input["code"]
                )
                return await self.async_step_products()

            except LoginError as exc:
                _LOGGER.debug("2FA error: %s", exc)
                errors["base"] = "invalid_2fa"

            except Exception as exc:
                _LOGGER.exception("Unexpected error during 2FA: %s", exc)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="twofa",
            data_schema=_TWOFA_SCHEMA,
            errors=errors,
            description_placeholders={"method": "SMS/WhatsApp"},
        )

    # ------------------------------------------------------------------
    # Step 3 — product selection
    # ------------------------------------------------------------------

    async def async_step_products(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if not self._product_options:
            try:
                self._product_options = await self.hass.async_add_executor_job(
                    _gather_products, self._client
                )
            except Exception as exc:
                _LOGGER.exception("Failed to fetch product list: %s", exc)
                errors["base"] = "cannot_fetch_products"

        if not self._product_options and not errors:
            errors["base"] = "no_products_available"

        if user_input is not None and not errors:
            selected: list[str] = user_input.get(CONF_SELECTED_PRODUCTS, [])
            if not selected:
                errors[CONF_SELECTED_PRODUCTS] = "no_products_selected"
            else:
                await self.async_set_unique_id(self._username.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self._username,
                    data={
                        "username": self._username,
                        "password": self._password,
                        CONF_COOKIES: self._client.get_cookies(),
                        CONF_SELECTED_PRODUCTS: selected,
                    },
                )

        return self.async_show_form(
            step_id="products",
            data_schema=_product_select_schema(self._product_options, []),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Options flow — shown when the user clicks "Configure" on the integration
# ---------------------------------------------------------------------------

class AfrihostOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to add or remove products after initial setup."""

    def __init__(self) -> None:
        self._product_options: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        # Re-use the already-authenticated client from the running coordinator
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

        if not self._product_options:
            if coordinator is not None:
                try:
                    self._product_options = await self.hass.async_add_executor_job(
                        _gather_products, coordinator.client
                    )
                except Exception as exc:
                    _LOGGER.exception("Failed to fetch product list: %s", exc)
                    errors["base"] = "cannot_fetch_products"
            else:
                errors["base"] = "cannot_fetch_products"

        if not self._product_options and not errors:
            errors["base"] = "no_products_available"

        current = (
            self.config_entry.options.get(CONF_SELECTED_PRODUCTS)
            or self.config_entry.data.get(CONF_SELECTED_PRODUCTS, [])
        )

        if user_input is not None and not errors:
            selected: list[str] = user_input.get(CONF_SELECTED_PRODUCTS, [])
            if not selected:
                errors[CONF_SELECTED_PRODUCTS] = "no_products_selected"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_SELECTED_PRODUCTS: selected},
                )

        return self.async_show_form(
            step_id="init",
            data_schema=_product_select_schema(self._product_options, current),
            errors=errors,
        )
