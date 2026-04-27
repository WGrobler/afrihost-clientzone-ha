# Afrihost — Home Assistant integration

Custom component for [Home Assistant](https://www.home-assistant.io/) that exposes your Afrihost ClientZone products as sensors.

## Requirements

Install the `pyafrihostapi` Python package into Home Assistant before enabling the integration:

```bash
pip install pyafrihostapi
```

For development, install from the local source:

```bash
pip install /path/to/afrihost_clientzone/pyafrihostapi
```

## Installation

Place the `custom_components/afrihost` folder into your Home Assistant `custom_components` directory, then restart Home Assistant.

Alternatively, add this repository to [HACS](https://hacs.xyz/) as a custom repository.

## Setup

1. Go to **Settings → Devices & Services → Add Integration** and search for **Afrihost**.
2. Enter your Afrihost ClientZone email and password.
3. If two-factor authentication is enabled on your account, enter the OTP code sent to your SMS/WhatsApp number.
4. Select which products to add as sensors and click **Submit**.

## Sensors

Each selected product becomes a sensor in Home Assistant:

| Product type | Sensor value | Extra attributes |
|---|---|---|
| LTE / Wireless | % used | bandwidth limit, % left, status |
| Mobile Data (APN) | % used | bandwidth limit, % left, status |
| Mobile SIM | status | UID (MSISDN), plan, price |
| VoIP | status | number (UID), plan, price |
| Device | friendly status | description, product name, serial number |
| Hosting | disk % used | remaining bytes, % available |

## Notes

- Data is polled from the Afrihost ClientZone API every 30 minutes.
- If the saved session expires, Home Assistant will automatically attempt a fresh login using stored credentials.
- If re-authentication fails (e.g. 2FA is required), the integration will raise an authentication error and you will need to reconfigure it.
