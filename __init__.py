"""The Muller Intuitiv Climate Integration integration."""

DOMAIN = "mullerintuitiv"


async def async_setup(hass, config):
    hass.states.async_set("mullerintuitiv.world", "Paulus")

    # Return boolean to indicate that initialization was successful.
    return True
