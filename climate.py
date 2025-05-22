"""The IntuisNetatmo climate integration for Home Assistant."""
from __future__ import annotations
XXX

import logging
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_PASSWORD,
    CONF_USERNAME,
    PRECISION_TENTHS,
    TEMP_CELSIUS,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType


_LOGGER = logging.getLogger(__name__)

# Configuration schema
CONFIG_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_CLIENT_ID): cv.string,
    vol.Required(CONF_CLIENT_SECRET): cv.string,
})

# Service schema for setting temperature
SERVICE_SET_TEMPERATURE = "set_temperature"
SERVICE_SET_TEMPERATURE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEMPERATURE): vol.Coerce(float),
})

# Map IntuisNetatmo modes to Home Assistant modes
MODE_MAP = {
    "program": HVACMode.AUTO,
    "manual": HVACMode.HEAT,
    "off": HVACMode.OFF,
    "hg": HVACMode.OFF,  # Frost protection
}

# Map IntuisNetatmo modes to Home Assistant actions
ACTION_MAP = {
    "program": HVACAction.IDLE,
    "manual": HVACAction.HEATING,
    "off": HVACAction.IDLE,
    "hg": HVACAction.IDLE,
}

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the IntuisNetatmo climate platform."""
    # Create IntuisNetatmo client
    client = IntuisNetatmo(
        username=config[CONF_USERNAME],
        password=config[CONF_PASSWORD],
        client_id=config[CONF_CLIENT_ID],
        client_secret=config[CONF_CLIENT_SECRET],
    )

    # Pull initial data
    client.pull_data()

    # Create climate entities for each room
    entities = []
    for room in client.rooms.values():
        entities.append(IntuisNetatmoClimate(client, room))

    async_add_entities(entities)

    # Register service for setting temperature
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_TEMPERATURE,
        SERVICE_SET_TEMPERATURE_SCHEMA,
        "async_set_temperature",
    )

class IntuisNetatmoClimate(ClimateEntity):
    """Representation of an IntuisNetatmo climate device."""

    def __init__(self, client: IntuisNetatmo, room: Any) -> None:
        """Initialize the climate device."""
        self._client = client
        self._room = room
        self._attr_name = room.name
        self._attr_unique_id = f"intuis_netatmo_{room.id}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = PRECISION_TENTHS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.PRESET_MODE
        )
        self._attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
        self._attr_preset_modes = ["program", "manual", "off", "hg"]
        self._attr_min_temp = 7.0  # Minimum temperature (frost protection)
        self._attr_max_temp = 30.0  # Maximum temperature

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._room.current_temp

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._room.target_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation mode."""
        return MODE_MAP.get(self._room.mode, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running hvac operation."""
        return ACTION_MAP.get(self._room.mode, HVACAction.IDLE)

    @property
    def preset_mode(self) -> Optional[str]:
        """Return the current preset mode."""
        return self._room.mode

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            self._client.set_room_setpoint(self._room.id, temperature)
            self._room.target_temp = temperature
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error setting temperature: %s", err)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        mode_map_reverse = {v: k for k, v in MODE_MAP.items()}
        mode = mode_map_reverse.get(hvac_mode)
        if mode is None:
            return

        try:
            if mode == "manual":
                # Set to manual mode with current target temperature
                self._client.set_room_mode(
                    self._room.id,
                    mode,
                    self._room.target_temp or 20.0
                )
            else:
                self._client.set_room_mode(self._room.id, mode)
            self._room.mode = mode
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error setting HVAC mode: %s", err)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        try:
            if preset_mode == "manual":
                # Set to manual mode with current target temperature
                self._client.set_room_mode(
                    self._room.id,
                    preset_mode,
                    self._room.target_temp or 20.0
                )
            else:
                self._client.set_room_mode(self._room.id, preset_mode)
            self._room.mode = preset_mode
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error setting preset mode: %s", err)

    async def async_update(self) -> None:
        """Update the state of the climate entity."""
        try:
            self._client.get_homestatus()
            # Find the updated room status
            for room in self._client.rooms.values():
                if room.id == self._room.id:
                    self._room = room
                    break
        except Exception as err:
            _LOGGER.error("Error updating climate entity: %s", err) 
