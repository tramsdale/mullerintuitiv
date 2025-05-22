import requests
import json
from typing import Dict, Optional, Union
from datetime import datetime, timedelta


class IntuisNetatmo:
    def __init__(
        self,
        username: str,
        password: str,
        client_id: str,
        client_secret: str,
        base_url: str = "https://app.muller-intuitiv.net",
    ):
        self.do_init(username, password, client_id, client_secret, base_url)

    def __init__(self, base_url: str = "https://app.muller-intuitiv.net"):
        """
        Initialize the IntuisNetatmo client.

        Args:
            username (str): Your Intuis account username
            password (str): Your Intuis account password
            client_id (str): Your Intuis client ID
            client_secret (str): Your Intuis client secret
            base_url (str): Base URL for the Intuis API
        """
        try:
            with open("secrets.json") as f:
                secrets = json.load(f)
            username = secrets.get("username")
            password = secrets.get("password")
            client_id = secrets.get("client_id")
            client_secret = secrets.get("client_secret")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError(
                "Missing credentials and could not load from secrets.json"
            ) from e

        if not all([username, password, client_id, client_secret]):
            raise ValueError(
                "Missing required credentials. Please provide all credentials or ensure they are in secrets.json"
            )

        self.do_init(username, password, client_id, client_secret, base_url)

    def do_init(self, username, password, client_id, client_secret, base_url):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self.token = None
        self.refresh_token = None
        self.token_expiry = None
        self.homesdata = None
        self.home_id = None
        self.home_name = None
        self.homestatus = None
        self.router_id = None
        self.rooms = {}  # Dictionary to store IntuisRoom objects, keyed by room ID
        self.water_heaters = {}  # Dictionary to store WaterHeater objects, keyed by module ID
        self.measures = None

    def _get_token(self) -> str:
        """
        Get or refresh the authentication token.

        Returns:
            str: Authentication token
        """
        if (
            self.token
            and self.token_expiry
            and datetime.now().timestamp() < self.token_expiry
        ):
            return self.token

        url = f"{self.base_url}/oauth2/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "password",
            "user_prefix": "muller",
            "scope": "read_muller write_muller",
            "username": self.username,
            "password": self.password,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = self.session.post(url, data=data, headers=headers)
        response.raise_for_status()

        result = response.json()
        self.token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        # Assuming token expires in 1 hour
        self.token_expiry = datetime.now().timestamp() + 3600

        return self.token

    def pull_data(self):
        """
        Pull all initial data from the Intuis API, and setup internal structures
        """
        self.get_homesdata()
        self.get_homestatus()

    def get_homesdata(self) -> Dict:
        """
        Get data about all homes associated with the account.

        Returns:
            Dict: Homes data and their information
        """
        token = self._get_token()
        url = f"{self.base_url}/api/homesdata"
        headers = {"Authorization": f"Bearer {token}"}

        response = self.session.get(url, headers=headers)
        response.raise_for_status()

        # Parse out the required info...
        self.homesdata = response.json()
        self.home_id = self.homesdata["body"]["homes"][0]["id"]
        self.home_name = self.homesdata["body"]["homes"][0]["name"]
        # Find the first NMG module (router) and store its ID
        for module in self.homesdata["body"]["homes"][0]["modules"]:
            if module.get("type") == "NMG":
                self.router_id = module.get("id")
                break
        # Create IntuisRoom instances for each room
        self.rooms = {}
        for room in self.homesdata["body"]["homes"][0]["rooms"]:
            if "module_ids" in room and room["module_ids"]:
                room_id = room["id"]
                room_name = room["name"]
                room_type = room["type"]
                intuis_room = None
                intuis_water_heater = None
                for module_id in room["module_ids"]:
                    # Find the module in the homesdata and add it to the room
                    for module in self.homesdata["body"]["homes"][0]["modules"]:
                        if module["id"] == module_id:
                            if module["type"] == "NMH":
                                if intuis_room == None:
                                    intuis_room = IntuisRoom(
                                        room_id=room_id,
                                        room_name=room_name,
                                        room_type=room_type,
                                    )
                                intuis_room.add_module(
                                    module
                                )  # Pass the entire module dictionary
                            elif module["type"] == "NMW":
                                if intuis_water_heater == None:
                                    intuis_water_heater = IntuisWaterHeater(
                                        room_id=room_id,
                                        heater_id=module_id,
                                        heater_name=room_name,
                                    )
                            else:
                                print(
                                    f"Warning: Unknown module type {module['type']} for room {room_name}"
                                )

                            break
                # Add modules to the room if any are defined
                if intuis_room:
                    self.rooms[room_id] = intuis_room
                    print(f"Added room: {str(intuis_room)}")
                if intuis_water_heater:
                    self.water_heaters[room_id] = intuis_water_heater
                    print(f"Added water heater: {str(intuis_water_heater)}")

        return response.json()

    def get_homestatus(self) -> Dict:
        """
        Get current status of the home including rooms and modules.

        Returns:
            Dict: Home status information including rooms and modules
        """
        token = self._get_token()
        url2 = f"{self.base_url}/syncapi/v1/homestatus"
        url1 = f"{self.base_url}/syncapi/v1/getconfigs"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"home_id": self.home_id}

        response = self.session.post(url1, headers=headers, data=data)
        response.raise_for_status()
        response = self.session.post(url2, headers=headers, data=data)
        response.raise_for_status()
        self.homestatus = response.json()

        # Update room statuses
        for room in self.rooms.values():
            # Find matching room status by room ID
            matching_room = next(
                (
                    r
                    for r in self.homestatus["body"]["home"]["rooms"]
                    if r["id"] == room.id
                ),
                None,
            )
            if matching_room:
                room.update_status(matching_room)
            else:
                print(f"Warning: No status found for room {room.id}")

        # Update water heater statuses
        for water_heater in self.water_heaters.values():
            matching_water_heater = next(
                (
                    r
                    for r in self.homestatus["body"]["home"]["modules"]
                    if r["id"] == water_heater.id
                ),
                None,
            )
            if matching_water_heater:
                water_heater.update_status(matching_water_heater)
            else:
                print(f"Warning: No status found for water heater {water_heater.id}")

        return response.json()

    def print_home_info(self) -> None:
        """
        Print information about the home including home name, ID and all rooms.
        """
        print(f"\nHome Name: {self.homesdata['body']['homes'][0]['name']}")
        print(f"Home ID: {self.home_id}")
        print("\nRooms:")
        for room in self.rooms.values():
            print(f"  {str(room)}")
        print("\nWater Heaters:")
        for water_heater in self.water_heaters.values():
            print(f"  {str(water_heater)}")

    def write_json_to_file(self, data: Dict, filename: str) -> None:
        """
        Write JSON data to a debug file.

        Args:
            data (Dict): JSON data to write
            filename (str): Name of file to write to
        """
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error writing debug file {filename}: {str(e)}")

    def write_debug_files(self) -> None:
        """
        Write homestatus and homesdata to debug JSON files.
        """
        if hasattr(self, "homestatus"):
            self.write_json_to_file(self.homestatus, "homestatus_debug.json")
        if hasattr(self, "homesdata"):
            self.write_json_to_file(self.homesdata, "homesdata_debug.json")
        if hasattr(self, "measures"):
            self.write_json_to_file(self.measures, "measures_debug.json")

    def get_home_measure(self, scale: str = "30min"):
        """
        Get measurements for the home.

        Args:
            scale (str): Time scale for measurements (e.g., "1hour", "1day", "1week")

        Returns:
            Dict: Home measurements data
        """
        token = self._get_token()
        print(token)
        url = f"{self.base_url}/api/gethomemeasure"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        data = {
            "date_end": int(datetime.now().timestamp()),
            "date_begin": int((datetime.now() - timedelta(hours=24)).timestamp()),
            "app_identifier": "app_muller",
            "scale": scale,
            "real_time": True,
            "home": {"id": self.home_id, "rooms": []},
        }
        # Add rooms data with bridge and measurement types
        types = [
            "sum_energy_elec_hot_water",
            "sum_energy_elec_heating",
            "sum_energy_elec",
            "sum_energy_elec$0",
            "sum_energy_elec$1",
            "sum_energy_elec$2",
        ]
        for room in self.rooms.values():
            data["home"]["rooms"].append(
                {"id": room.id, "bridge": self.router_id, "type": types}
            )
        for water_heater in self.water_heaters.values():
            data["home"]["rooms"].append(
                {"id": water_heater.room_id, "bridge": self.router_id, "type": types}
            )
        print(data)
        response = self.session.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        print(response.json())
        self.measures = response.json()
        return response.json()

    def set_room_setpoint(
        self, room_id: str, temp: float, end_time: Optional[int] = None
    ) -> Dict:
        """
        Set a manual temperature setpoint for a specific room.

        Args:
            room_id (str): ID of the room to set temperature for
            temp (float): Target temperature in Celsius
            end_time (int, optional): Unix timestamp when setpoint should end. If None, setpoint remains until next schedule.

        Returns:
            Dict: Response from the API
        """
        token = self._get_token()
        url = f"{self.base_url}/syncapi/v1/setstate"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {
            "home": {
                "id": self.home_id,
                "rooms": [
                    {
                        "id": room_id,
                        "therm_setpoint_mode": "manual",
                        "therm_setpoint_temperature": temp,
                    }
                ],
            }
        }

        if end_time:
            data["home"]["rooms"][0]["therm_setpoint_end_time"] = end_time

        response = self.session.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()

    def set_room_off(self, room_id: str) -> Dict:
        """
        Set a room to off mode with minimum temperature (7°C frost protection).

        Args:
            room_id (str): ID of the room to turn off

        Returns:
            Dict: Response from the API
        """
        token = self._get_token()
        url = f"{self.base_url}/syncapi/v1/setstate"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {
            "home": {
                "id": self.home_id,
                "rooms": [
                    {
                        "id": room_id,
                        "therm_setpoint_mode": "off",
                        "therm_setpoint_temperature": 7,
                    }
                ],
            }
        }

        response = self.session.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()

    def set_room_hg(self, room_id: str) -> Dict:
        """
        Set a room to HG (Hors Gel/Frost Protection) mode with minimum temperature (7°C).

        Args:
            room_id (str): ID of the room to set to frost protection mode

        Returns:
            Dict: Response from the API
        """
        token = self._get_token()
        url = f"{self.base_url}/api/setroomthermpoint"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {
            "home": {
                "id": self.home_id,
                "rooms": [
                    {
                        "id": room_id,
                        "therm_setpoint_mode": "hg",
                        "therm_setpoint_temperature": 7,
                    }
                ],
            }
        }

        response = self.session.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()

    def get_room_id_by_name(self, room_name: str) -> str:
        """
        Look up a room's ID by its name.

        Args:
            room_name (str): Name of the room to find

        Returns:
            str: Room ID if found, None if not found

        Raises:
            ValueError: If homesdata has not been loaded yet
        """
        if not self.homesdata:
            raise ValueError("Must call pull_data() or get_homesdata() first")

        for room in (
            self.homesdata.get("body", {}).get("homes", [{}])[0].get("rooms", [])
        ):
            if room.get("name", "").lower() == room_name.lower():
                return room.get("id")
        return None

    def set_room_mode(self, room_id: str, mode: str, temperature: float = None) -> Dict:
        """
        Set the mode for a room.

        Args:
            room_id (str): ID of the room to set the mode for
            mode (str): Mode to set - one of: program, away, hg (frost protection), manual
            temperature (float, optional): Temperature to set if using manual mode

        Returns:
            Dict: Response from the API

        Raises:
            ValueError: If using manual mode without temperature or invalid mode
        """
        valid_modes = ["program", "away", "hg", "manual"]
        if mode not in valid_modes:
            raise ValueError(f"Mode must be one of: {', '.join(valid_modes)}")

        if mode == "manual" and temperature is None:
            raise ValueError("Temperature must be specified when using manual mode")

        token = self._get_token()
        url = f"{self.base_url}/api/setroomthermpoint"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {
            "home": {
                "id": self.home_id,
                "rooms": [{"id": room_id, "therm_setpoint_mode": mode}],
            }
        }

        if mode == "manual":
            data["home"]["rooms"][0]["therm_setpoint_temperature"] = temperature

        response = self.session.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()

    def get_room_mode(self, room_id: str) -> Dict:
        """
        Get the current mode and settings for a room.

        Args:
            room_id (str): ID of the room to get the mode for

        Returns:
            Dict: Room status information including mode and temperature settings

        Raises:
            ValueError: If room_id is not found in homestatus
        """
        if not self.homestatus:
            self.get_homestatus()

        for room in self.homestatus["body"]["home"]["rooms"]:
            if room["id"] == room_id:
                return {
                    "mode": room["therm_setpoint_mode"],
                    "current_temp": room["therm_measured_temperature"],
                    "target_temp": room["therm_setpoint_temperature"],
                    "end_time": room["therm_setpoint_end_time"],
                }

        raise ValueError(f"Room ID {room_id} not found")

    def get_room_setpoint(self, room_id: str) -> Dict:
        """
        Get the current temperature setpoint for a room.

        Args:
            room_id (str): ID of the room to get the setpoint for

        Returns:
            Dict: Room setpoint information including target temperature and end time

        Raises:
            ValueError: If room_id is not found in homestatus
        """
        if not self.homestatus:
            self.get_homestatus()

        for room in self.homestatus["body"]["home"]["rooms"]:
            if room["id"] == room_id:
                return {
                    "target_temp": room["therm_setpoint_temperature"],
                    "end_time": room["therm_setpoint_end_time"],
                }

        raise ValueError(f"Room ID {room_id} not found")

    def get_room_temperature(self, room_id: str) -> float:
        """
        Get the current measured temperature for a room.

        Args:
            room_id (str): ID of the room to get the temperature for

        Returns:
            float: Current measured temperature in Celsius

        Raises:
            ValueError: If room_id is not found in homestatus
        """
        if not self.homestatus:
            self.get_homestatus()

        for room in self.homestatus["body"]["home"]["rooms"]:
            if room["id"] == room_id:
                return room["therm_measured_temperature"]

        raise ValueError(f"Room ID {room_id} not found")

    def get_water_heater_mode(self, water_heater_id: str) -> str:
        """
        Get the current mode of a water heater.

        Args:
            water_heater_id (str): ID of the water heater module

        Returns:
            str: Current mode of the water heater ('auto' or 'manual')

        Raises:
            ValueError: If water_heater_id is not found in homestatus
        """
        if not self.homestatus:
            self.get_homestatus()

        for module in self.homestatus["body"]["home"]["modules"]:
            if module["id"] == water_heater_id and module["type"] == "NMW":
                return module["contactor_mode"]

        raise ValueError(f"Water heater ID {water_heater_id} not found")

    def set_water_heater_mode(self, water_heater_id: str, mode: str) -> Dict:
        """
        Set the mode of a water heater.

        Args:
            water_heater_id (str): ID of the water heater module
            mode (str): Mode to set ('auto' or 'manual')

        Returns:
            Dict: Response from the API

        Raises:
            ValueError: If mode is not 'auto' or 'manual'
        """
        if mode not in ["auto", "manual"]:
            raise ValueError("Mode must be 'auto' or 'manual'")

        token = self._get_token()
        url = f"{self.base_url}/api/setcontactormode"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {
            "home": {
                "id": self.home_id,
                "modules": [{"id": water_heater_id, "contactor_mode": mode}],
            }
        }

        response = self.session.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()


class IntuisRoom:
    """Class representing an Intuis room thermostat"""

    def __init__(self, room_id: str, room_name: str, room_type: str):
        """Initialize room thermostat

        Args:
            room_id (str): Unique identifier for the room
            room_name (str): Display name of the room
            room_type (str): Type of room (e.g. bedroom, living room etc)
        """
        self.id = room_id
        self.name = room_name
        self.type = room_type
        self.current_temp = None
        self.target_temp = None
        self.mode = None
        self.heating_power = None
        self.energy_consumption = None
        self.associated_modules = []

    def update_status(self, room_status: dict) -> None:
        """Update room status from API response

        Args:
            room_status (dict): Room status data from API
        """
        self.current_temp = room_status.get("therm_measured_temperature")
        self.target_temp = room_status.get("therm_setpoint_temperature")
        self.mode = room_status.get("therm_setpoint_mode")
        self.heating_power = room_status.get("heating_power_request")
        if "energy" in room_status:
            self.energy_consumption = room_status["energy"]

    def add_module(self, module: dict) -> None:
        """Add an associated module to the room

        Args:
            module (dict): Module data from API
        """
        self.associated_modules.append(
            {
                "id": module.get("id"),
                "name": module.get("name"),
                "type": module.get("type"),
            }
        )

    def __str__(self) -> str:
        """String representation of room status"""
        status = f"Room: {self.name} ({self.type})\n"
        status += f"- ID: {self.id}\n"
        status += f"- Current Temperature: {self.current_temp}°C\n"
        status += f"- Target Temperature: {self.target_temp}°C\n"
        status += f"- Mode: {self.mode}\n"
        status += f"- Heating Power: {self.heating_power}\n"
        status += f"- Energy Consumption: {self.energy_consumption} kWh\n"
        if self.associated_modules:
            status += "- Associated Modules:\n"
            for module in self.associated_modules:
                status += f"    - {module['name']} ({module['type']})\n"
        return status


class IntuisWaterHeater:
    """Class representing a Netatmo Intuis water heater device"""

    def __init__(self, heater_id: str, heater_name: str, room_id: str) -> None:
        """Initialize water heater

        Args:
            heater_id (str): ID of the water heater
        """
        self.id = heater_id
        self.room_id = room_id
        self.name = heater_name
        self.boiler_status = None
        self.connection_status = None
        self.contactor_mode = None
        self.firmware_revision = None
        self.last_seen = None
        self.bridge = None

    def update_status(self, heater_status: dict) -> None:
        """Update water heater status from API response

        Args:
            heater_status (dict): Water heater status data from API
        """
        self.boiler_status = heater_status.get("boiler_status")
        self.connection_status = heater_status.get("connection_status")
        self.contactor_mode = heater_status.get("contactor_mode")
        self.firmware_revision = heater_status.get("firmware_revision")
        self.last_seen = heater_status.get("last_seen")
        self.bridge = heater_status.get("bridge")

    def __str__(self) -> str:
        """String representation of water heater status"""
        status = f"Water Heater: {self.id} in room {self.room_id}\n"
        status += f"- Boiler Status: {'On' if self.boiler_status else 'Off'}\n"
        status += f"- Connection Status: {self.connection_status}\n"
        status += f"- Contactor Mode: {self.contactor_mode}\n"
        status += f"- Firmware Revision: {self.firmware_revision}\n"
        status += f"- Last Seen: {self.last_seen}\n"
        status += f"- Bridge: {self.bridge}\n"
        return status
