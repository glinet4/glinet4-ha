<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/glinet4/branding/main/assets/dark_logo.png">
    <img alt="glinet4" src="https://raw.githubusercontent.com/glinet4/branding/main/assets/logo.png" width="300">
  </picture>
</p>

# GL.iNet (glinet4) — Home Assistant integration

A Home Assistant custom integration for GL.iNet routers running firmware 4.x, using their local [JSON-RPC API](https://dev.gl-inet.com/api/). Powered by the [`glinet4`](https://github.com/glinet4/glinet4) Python library.

> This project (domain `glinet4`) began as a fork of [HarvsG/ha-glinet4-integration](https://github.com/HarvsG/ha-glinet4-integration) and its `gli4py` library, and has since grown a much larger feature set. It uses a distinct domain so it can be installed independently. See [NOTICE](NOTICE) for attribution.

Disclaimer: GL.iNet no longer publicly documents their API, so the longevity of this integration is unknown and may break with future firmware.

Contributions are welcome, for ideas see the TODO list below or the various `#TODO`s in the code.

## Features

- Device tracker for devices connected directly or indirectly to a GL.iNet router.
  - Note, modern phones use MAC address randomisation when they connect to WiFi, you will need to disable this for your home wifi only on [android](https://www.howtogeek.com/722653/how-to-disable-random-wi-fi-mac-address-on-android/) and [iphone](https://www.linksys.com/support-article?articleNum=317709)
- Control all configured wireguard and tailscale clients with a switch.
- Reboot your router
- System device sensors including CPU temperature (if supported by your device), CPU load and Uptime
- WAN sensors: public IP (with gateway/DNS/protocol attributes) and download/upload throughput (on firmware that exposes the WAN endpoints)
- Tailscale status sensor (disconnected / login required / authorization required / connected / connecting) with the login URL as an attribute when the router needs re-authentication
- Tailscale exit-node select: route the router's traffic through any exit node on your tailnet (or none)
- Firmware update entity: shows when GL.iNet publishes a newer firmware (checked at most every 6 hours; read-only by design)
- LED switch: turn the router's LEDs on or off
- Internet connectivity binary sensor (from the router's own per-interface online state)
- Per-client internet switch: block or allow any client's network access by MAC (disabled by default; enable per client)
- Flow statistics switch: enable/disable per-application traffic statistics, with an attribute explaining when data won't collect (NAT acceleration off due to QoS/SQM) — and a Repair notification when statistics are on but not collecting
- Repair notifications: Tailscale needs re-authentication (dropped from the tailnet), and router not in router mode (VPN/Tailscale features unavailable)
- Coming soon:
  - On/off control of WiFi Networks

## Installation

1. [Install HACS](https://www.youtube.com/watch?v=a4lSlN6EI04)
2. Open the HACS page in home assistant
3. Search for GL.iNet (glinet4) and download the latest release

## Development

See **[DEVELOPMENT.md](DEVELOPMENT.md)** for the full setup, and
[CONTRIBUTING.md](CONTRIBUTING.md) for the test suite and hooks.

In short: open the repo in a VS Code **Dev Container** (or Codespace) and run
`scripts/develop` to launch Home Assistant with this integration loaded, then add
it from the UI. A no-devcontainer path (`uv sync && scripts/develop`) is also
documented.

## Testing

```bash
scripts/test          # run the suite across every router profile
```

The suite is driven by per-model/firmware "profiles" under `tests/fixtures/` and
runs every test against each one. To add a router, capture it with
`scripts/capture-fixtures` (it sanitises MACs/IPs/secrets) and the suite picks it
up automatically. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## TODO

- [ ] Handle all the errors gracefully, including empty client lists that happen after a glinet device restart.
- [ ] Auto detect router IP for config flow - assume it is the default gateway, test an endpoint that doesn't require auth (/model or /hello), fallback to default `192.168.8.1`
- [ ] Add switches for wireguard and open vpn (client and server), done for wireguard client, but we can probably do all programmatically rather than repeating boilerplate
  - worth considering you can have multiple clients, most of the API endpoints act on the last used client config. Can we get a list from the API and create switches for all? Maybe (router/vpn/status?)
- [x] Allow deletion of unhelpful device tracker devices/entities, [docs](https://developers.home-assistant.io/docs/device_registry_index/#removing-devices), [example](https://github.com/home-assistant/core/pull/73293/commits/9c253c6072cf60f92228051d918fd550d38b6ac3)
- [ ] Enable strict type checking with mypy and a github action
- [x] Add tests - will need to mock the API
- [x] Detect and create a re-configure entry if the password changes (reauth flow)
- [ ] Enable support for `https` as well as `http` and consider enabling it by default.
- [ ] Static type glinet4 and then enable static typing on this repo
- [ ] Add features:
  - [x] Upload/Download sensors (WAN throughput)
  - [x] Internet reachable sensor (binary_sensor from system get_network_status)
  - [x] Public IP sensor (WAN IP)
  - [x] Tailscale status + re-auth URL, exit-node select
  - [x] Firmware update available indicator (update entity)
- [ ] Features under consideration
  - Making changes to the VPN client policies would be cool to automate switching on/off VPN use per device in automations. Useful for bypassing geofilters for example
  - Firmware upgrades https://dev.gl-inet.com/api/#api-firmware (should have warnings)
  - [x] Switch for LED control (done)
  - Tethering controls:https://dev.gl-inet.com/api/#api-tethering
  - Modem control (useful for failover internet automations)
  - ?SMS control - maybe a notify platform [see example](https://github.com/home-assistant/core/blob/dev/homeassistant/components/sms/notify.py)
  - Explore using the smarthome BLE endpoints: https://dev.gl-inet.com/api/#api-SmartHome

## Tested on

- Beryl MT3000
- Convexa B1300
- Flint 2 MT6000 (firmware 4.9.0)

## Depends on

https://github.com/glinet4/glinet4

---

Part of the **[glinet4](https://github.com/glinet4)** project — [glinet4](https://github.com/glinet4/glinet4) (Python library) · [glinet4-ha](https://github.com/glinet4/glinet4-ha) (Home Assistant) · [glinet4-profiler](https://github.com/glinet4/glinet4-profiler) · [glinet4-registry](https://github.com/glinet4/glinet4-registry)
