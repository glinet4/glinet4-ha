"""Config flow for GL.iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from glinet4 import GLinet
from glinet4.error_handling import (
    AuthenticationError,
    FeatureConflictError,
    TokenError,
    UnexpectedResponse,
    UnsuccessfulRequest,
)
from homeassistant import config_entries
from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
)
from homeassistant.const import (
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .const import (
    API_PATH,
    CONF_TITLE,
    DOMAIN,
    GLINET_DEFAULT_PW,
    GLINET_DEFAULT_URL,
    GLINET_DEFAULT_USERNAME,
    GLINET_FRIENDLY_NAME,
)
from .utils import adjust_mac

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_USERNAME, default=GLINET_DEFAULT_USERNAME
        ): selector.TextSelector(),
        vol.Required(CONF_HOST, default=GLINET_DEFAULT_URL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
        vol.Required(CONF_PASSWORD, default=GLINET_DEFAULT_PW): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Optional(
            CONF_CONSIDER_HOME, default=DEFAULT_CONSIDER_HOME.total_seconds()
        ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=900)),
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=GLINET_DEFAULT_USERNAME): (
            selector.TextSelector()
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class TestingHub:
    """Testing class to test connection and authentication."""

    def __init__(self, username: str, host: str, hass: HomeAssistant) -> None:
        """Initialize."""
        self.host: str = host
        self.username: str = username
        self.router: GLinet = GLinet(
            base_url=self.host + API_PATH,
            session=async_get_clientsession(hass),
        )
        self.router_mac: str = ""
        self.router_model: str = ""

    async def connect(self) -> bool:
        """Test if we can communicate with the host.

        ``router_reachable()`` already swallows every ``APIClientError``
        subclass internally and returns ``False``, so these except clauses
        are defensive rather than live paths; they exist to log a useful
        reason (instead of falling through silently) should that contract
        ever change.
        """
        try:
            res: bool = await self.router.router_reachable(self.username)
        except UnsuccessfulRequest:
            _LOGGER.exception(
                "Failed to connect to %s, is it really a GL.iNet router?", self.host
            )
        except UnexpectedResponse:
            _LOGGER.exception(
                "Failed to parse router response to %s, is it the right firmware version?",
                self.host,
            )
        else:
            _LOGGER.info("Attempting to connect to router, success:%s", res)
            return res
        return False

    async def authenticate(self, password: str) -> bool:
        """Test if we can authenticate with the host.

        Bad credentials (``AuthenticationError``/``TokenError``) are
        swallowed: they're expected here, e.g. while probing a DHCP-discovered
        router's default password. A transport failure
        (``UnsuccessfulRequest``) is left to propagate to ``validate_input``,
        which reports it as ``cannot_connect`` rather than a credentials
        problem.
        """
        try:
            await self.router.login(self.username, password)
            res = await self.router.router_info()
        except (AuthenticationError, TokenError):
            _LOGGER.info(
                "Failed to authenticate with GL.iNet router during testing, this may be expected at times"
            )
        except FeatureConflictError:
            _LOGGER.exception(
                "GL.iNet router %s reported a feature conflict while testing authentication",
                self.host,
            )
            raise
        else:
            self.router_mac = res["mac"]
            self.router_model = res["model"]
        return bool(self.router.logged_in)


async def validate_input(
    data: dict[str, Any], hass: HomeAssistant, raise_on_invalid_auth: bool = True
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    hub = TestingHub(
        data.get(CONF_USERNAME, GLINET_DEFAULT_USERNAME), data[CONF_HOST], hass
    )

    if not await hub.connect():
        raise CannotConnect

    valid_auth = True
    try:
        authenticated = await hub.authenticate(
            data.get(CONF_PASSWORD, GLINET_DEFAULT_PW)
        )
    except UnsuccessfulRequest as err:
        # The router answered connect()'s reachability check but dropped off
        # the network before/during login; that's a transport failure, not
        # bad credentials.
        raise CannotConnect from err
    if not authenticated:
        valid_auth = False
    if raise_on_invalid_auth and not valid_auth:
        raise InvalidAuth

    # Return info that you want to store in the config entry.
    return {
        # TODO, on success we can/should probably store some immutable device info in the class.
        CONF_TITLE: GLINET_FRIENDLY_NAME + " " + hub.router_model.upper(),
        CONF_MAC: hub.router_mac,
        "data": {
            CONF_USERNAME: data.get(CONF_USERNAME, GLINET_DEFAULT_USERNAME),
            CONF_HOST: data[CONF_HOST],
            CONF_API_TOKEN: hub.router.sid,
            CONF_PASSWORD: (
                data.get(CONF_PASSWORD, GLINET_DEFAULT_PW) if valid_auth else ""
            ),
            CONF_CONSIDER_HOME: data.get(
                CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()
            ),
        },
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GL.iNet."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_data = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""

        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(user_input, self.hass)
                # In future we could do additional checks such as
                # decting API version warning about unsupported versions
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            # Broad excepts are permitted in config flows
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                unique_id: str = format_mac(info[CONF_MAC])
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info[CONF_TITLE], data=info["data"]
                )

        # If we have discovered data, we can pre-fill the form
        defaults = user_input or self._discovered_data or {}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, defaults
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the router host and/or credentials of an existing entry.

        Keeps the same device: if the entered router reports a different MAC,
        the flow aborts rather than repointing the entry at another router.
        """
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(user_input, self.hass)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            # Broad excepts are permitted in config flows
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(format_mac(info[CONF_MAC]))
                self._abort_if_unique_id_mismatch(reason="unique_id_mismatch")
                return self.async_update_reload_and_abort(
                    reconfigure_entry, data_updates=info["data"]
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {
                    CONF_HOST: reconfigure_entry.data.get(CONF_HOST),
                    CONF_USERNAME: reconfigure_entry.data.get(CONF_USERNAME),
                },
            ),
            errors=errors,
        )

    async def async_step_reauth(self, _: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication when the stored token is rejected.

        Triggered by the coordinator raising ``ConfigEntryAuthFailed``; prompts
        for fresh credentials and refreshes the stored token in place.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication with a freshly entered password."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**reauth_entry.data, **user_input}
            try:
                info = await validate_input(data, self.hass)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            # Broad excepts are permitted in config flows
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=info["data"]
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_REAUTH_DATA_SCHEMA,
                {CONF_USERNAME: reauth_entry.data.get(CONF_USERNAME)},
            ),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle information passed following a DHCP discovery."""

        _LOGGER.debug(
            "DHCP device discovered with host: %s, ip: %s and mac: %s",
            discovery_info.hostname,
            discovery_info.ip,
            discovery_info.macaddress,
        )
        # This is probably not robust to https and those using a hostname
        discovery_input = {CONF_HOST: f"http://{discovery_info.ip}"}
        self._async_abort_entries_match(discovery_input)
        # confirm that this is running a compatible version of the API

        # the factory mac is usually the LAN MAC -1
        unique_id = adjust_mac(discovery_info.macaddress, -1).lower()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        if {unique_id, format_mac(discovery_info.macaddress)}.intersection(
            self._async_current_ids(include_ignore=True)
        ):
            raise AbortFlow("already_configured")
        try:
            entry = await validate_input(
                discovery_input, raise_on_invalid_auth=False, hass=self.hass
            )
        except CannotConnect:
            _LOGGER.debug("Failed to connect to DHCP device, aborting")
        else:
            _LOGGER.debug(
                "Connected to device using DHCP information, default password in use: %s",
                entry["data"][CONF_PASSWORD] == GLINET_DEFAULT_PW,
            )
            entry["data"].pop(CONF_API_TOKEN)
            self._discovered_data = entry["data"]
            return await self.async_step_user()
        return self.async_abort(reason="cannot_connect")

    @staticmethod
    @callback
    def async_get_options_flow(
        _: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for GL.iNet."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle options flow."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(user_input, self.hass)
                # In future we could do additional checks such as
                # decting API version warning about unsupported versions
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            # Broad excepts are permitted in config flows
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="", data=self.config_entry.options | info["data"]
                )
        # This exposes the API key back to the user
        data_schema = self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA, self.config_entry.data
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
