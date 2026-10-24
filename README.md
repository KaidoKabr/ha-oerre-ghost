# Oerre Ghost for Home Assistant

Unofficial, local Home Assistant integration for **O.ERRE Ghost App** decentralised heat recovery units (Ghost 100 APP / Ghost 160 APP), the ones controlled with the **O.Tech** (formerly *O.APP*) mobile app.

> Not affiliated with or endorsed by O.ERRE / EP S.p.A. Use at your own risk.

## How it works

Ghost App units have no local API: they keep a permanent, unencrypted TCP connection to the Oerre cloud (`app-oerre.it`, port 11000) and the app talks to the cloud.

This integration turns Home Assistant into a **transparent proxy**:

```
Ghost unit ──► Home Assistant (port 11000) ──► Oerre cloud ◄── O.Tech app
                    │
                    └─ reads status, sends commands
```

- Every byte is forwarded unchanged, so **the O.Tech app keeps working**.
- Status (mode, speed, temperature, humidity, air quality, filter) is pushed by each unit about every 35 s.
- Commands from Home Assistant are injected into the same connection.
- If the cloud is unreachable, local control still works.

You redirect the units with **one local DNS record**. Delete the record and everything goes back to the original behaviour.

## Entities (per unit)

| Entity | Type | Notes |
|---|---|---|
| *(device name)* | `fan` | on/off, 3 speeds, mode as preset |
| Mode | `select` | Smart, Auto, Manual heat recovery, Night, Away, Surveillance, Timed extraction, Extraction, Intake, Master-slave flow, Slave-master flow, Off |
| Humidity threshold | `select` | Low / Medium / High (the *drop* slider in the app) |
| Twilight sensor | `select` | Off / Low / High (the *sun* slider in the app) |
| Temperature, Humidity | `sensor` | room values measured by the unit (°C in whole degrees) |
| Air quality | `sensor` | Very good / Good / Medium / Poor (the app's CO₂/VOC text) |
| Filter | `sensor` | OK / Check soon / Replace (the app's three filter squares) |
| Reset filter | `button` | same as RESET in the app |
| Active mode | `sensor` (diagnostic) | mode the unit is actually running |
| Connected | `binary_sensor` (diagnostic) | unit connected to Home Assistant |
| Raw status, Air quality raw | `sensor`, disabled | undecoded bytes for further research |

Units appear automatically the first time they connect. Rename them in Home Assistant.

Translations: English, Estonian.

## Installation

### HACS (custom repository)

1. HACS → three dots → **Custom repositories** → add `https://github.com/KaidoKabr/ha-oerre-ghost`, category **Integration**.
2. Install **Oerre Ghost**, restart Home Assistant.

### Manual

Copy `custom_components/oerre_ghost` to `<config>/custom_components/oerre_ghost` and restart Home Assistant.

## Setup

1. **Give Home Assistant a fixed IP address** (DHCP reservation).
2. **Settings → Devices & services → Add integration → Oerre Ghost.** Defaults are fine:
   - Listen port for units: `11000`
   - Oerre cloud host: `app-oerre.it` (resolved through public DNS, see below)
   - Oerre cloud port: `11000`
   - O.Tech app pass-through port: `4521`
3. **Add a local DNS record** in your router / DNS server:
   `app-oerre.it` → *A record* → *your Home Assistant IP*
   - UniFi Network: *Settings → Policy Engine → Policy Table → Create New Policy → DNS → Host (A)*
   - Pi-hole: *Local DNS → DNS Records*
   - AdGuard Home: *Filters → DNS rewrites*
   - Many routers: *LAN → DNS / Static DNS / Hostnames*
4. **Power-cycle each Ghost unit** (unplug for ~10 s). A Wi-Fi reconnect alone is usually not enough, the unit only looks up the server address when it boots.
5. Each unit shows up as a device within a minute.

Check: `nslookup app-oerre.it <router-ip>` must return your Home Assistant IP.

### Why public DNS?

Your local DNS now points `app-oerre.it` at Home Assistant, so Home Assistant cannot use it to find the real cloud. The integration asks 1.1.1.1 / 8.8.8.8 / 9.9.9.9 directly (plain DNS, UDP 53) and falls back to the last known address. If outbound DNS is blocked in your network, enter the cloud IP instead of the host name.

### Port 4521 (O.Tech app)

The app talks to the same server name on TCP 4521 (TLS). If your phone uses the local DNS, its connection also lands on Home Assistant; the integration passes it through to the cloud untouched. Set to `0` to disable.

## Master / slave pairs

The app can group two units into one zone (one blows in while the other extracts). In this case the app sends commands **only to the master** and the master drives the slave locally.

- Control the zone through the **master's** entities.
- The **slave's** filter value is not meaningful (it mirrors something else, while only the master has a filter warning light). Disable the slave's *Filter* entity and, optionally, its control entities. Temperature and humidity are valid.

Automatic slave detection is not implemented yet (needs more samples, see *Contributing*).

## Limitations

- If Home Assistant is down, units cannot reach the cloud and the O.Tech app shows them offline. The units keep running in their last mode.
- Tested with Ghost 100 APP and Ghost 160 APP firmware of October 2026 (5 units, one master/slave pair). Other firmware may differ.
- The *Check soon* filter state and *Poor* air quality code are inferred, not yet observed.

## Protocol (TCP 11000, unencrypted)

| Type | Direction | Length | Content |
|---|---|---|---|
| `03 00` + MAC | unit → cloud | 18 B | hello on connect |
| `01 00` + MAC | unit → cloud | 21 B | status, every ~35 s |
| `02 00` + MAC + `01` … | cloud → unit | 14 B | settings: `01 mode speed humidity twilight 01` |
| `02 00` + MAC + `03` | cloud → unit | 9 B | filter reset |

Status payload after the MAC (13 bytes): `mode, speed, humidity threshold, temperature (°C), humidity (%), air quality, ?, filter, ?, ?, active mode, twilight, ?`.

Modes: `00` Smart, `01` Auto, `02` Manual, `03` Night, `04` Away, `05` Surveillance, `06` Timed extraction, `07` Extraction, `08` Intake, `09` Master-slave, `0A` Slave-master, `0B` Off.
Speed `00–02`, humidity threshold `00–02`, twilight `01` (off) – `03`.
Air quality `00` very good, `01` good, `02` medium. Filter `00` OK, `02` replace.

## Contributing

Captures from other setups are very welcome, especially groups with more units, a slave unit, a yellow filter state or poor air quality. Enable the *Raw status* entity and open an issue with its value and what the app shows at the same time.

Run tests: `pip install -r requirements_test.txt && touch custom_components/__init__.py && pytest`

## Licence

MIT
