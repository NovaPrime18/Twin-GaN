# Twin-GaN

**Dual 3-phase GaN motor controller with on-board CAN traction control**

[![License: CERN-OHL-S v2.0](https://img.shields.io/badge/License-CERN--OHL--S%20v2.0-blue.svg)](https://ohwr.org/cern_ohl_s_v2.txt)
[![KiCad](https://img.shields.io/badge/Made%20with-KiCad-blue)](https://www.kicad.org/)

<table><tr>
<td><img src="https://raw.githubusercontent.com/NovaPrime18/Twin-GaN/main/Pics/twin-gan-f-n.png" width="100%"></td>
<td><img src="https://raw.githubusercontent.com/NovaPrime18/Twin-GaN/main/Pics/twin-gan-b.png" width="100%"></td>
</tr></table>
<img src="https://raw.githubusercontent.com/NovaPrime18/Twin-GaN/main/Pics/twin-gan-f.jpg" width="100%">

---

## Overview

Twin-GaN is an open-source, dual-motor VESC-compatible controller that fits two complete 3-phase inverters onto a single 99 × 99 mm board. It targets the same use case as a pair of off-the-shelf single ESCs — a two-wheel-drive skateboard, e-bike or robot — doing the job of two drivers with one board. It is **cheaper than the equivalent Flipsky dual, smaller, and more efficient**; the trade-off is deliberate, since it gives up peak power for that density. This is a 20 A-input board, not a 100 A one, and the density comes from switching to GaN rather than from oversizing the power stage.

Built around six EPC23102 eGaN ePower Stage ICs (100 V, 5.2 mΩ, gate driver and bootstrap integrated in a 3.5 × 5 mm package) and two STM32F405RGT6s, it accepts up to 60 VDC through a single XT60 and drives two motors through MR30PW-M connectors.

Both channels have their own MCU, their own USB-C port and their own three-shunt sensing chain, and all three controllers on the board (both STM32s plus an ESP32-C3-WROOM-02) share one internal CAN bus — which is what makes **traction control between the two channels** possible on-board, instead of two separate ESCs having to agree over a cable.

---

## Specifications

| Parameter | Value |
|---|---|
| Input voltage | up to 60 VDC |
| Battery input current | 20 A |
| Phase current | 20 A continuous / 40 A absolute max |
| Max input power | ≈ 1.2 kW (battery-limited: 60 V × 20 A, both channels) |
| PWM frequency | up to 35 kHz |
| Topology | 2 × independent 3-phase inverter |
| Power stage | 6 × EPC23102 ePower Stage (100 V, 5.2 mΩ) |
| Control | 2 × STM32F405RGT6 + 1 × ESP32-C3-WROOM-02 |
| Input connector | XT60 |
| Motor connectors | 2 × AMASS MR30PW-M (30 A) |
| Board | 99 × 99 mm, 4 layer, 1.6 mm |
| EDA | KiCad |

> ⚠️ **The current and power figures above are design targets for Revision 1 — they have not been bench-verified.**

---

## VESC-Tool Compatibility

- **Two independent VESC targets** — each channel runs its own STM32F405RGT6 with its own 6-PWM GaN stage, so VESC Tool detects, configures and monitors them as two separate controllers (VESC 75/300-derived hardware target)
- **USB-C per controller** — `J12`/`J13` give each motor its own USB-C for VESC Tool, with a third port (`J7`) on the ESP32-C3; every port has 5.1 kΩ CC pulldowns and VBUS → 0.5 A PTC → ferrite → diode → `+5V`
- **Three-shunt current sensing** — one INA240A1D per phase (six total) across 2 mΩ 1206 shunts, REF1 = GND / REF2 = `+3V3` for true bidirectional measurement
- **Hall sensors + motor temperature** — one 6-pin JST-PH header per channel (`J4`, `J9`): GND, Hall W, Hall V, Hall U, TEMP_MOTOR
- **VESC COMM header per channel** — 8-pin JST-PH (`J5`, `J10`) on the standard VESC accessory pinout: `+5V`, `+3V3`, GND, SCK, SDA/NSS, SCL/MOSI, MISO, ADC-15
- **SWD per controller** — Tag-Connect TC2030 footprints (`J2`, `J8`), no header needed
- **CAN** — three TJA1051T/3 transceivers on one internal bus (MCU1, MCU2 and the ESP32-C3), terminated on-board; the two channels can be coordinated for traction control over CAN
- **On-board UI** — one push button and red/green status LEDs per channel

---

## Hardware

| Component | Part |
|---|---|
| MCU | 2 × STM32F405RGT6 (LQFP-64) |
| Wireless / third CAN node | ESP32-C3-WROOM-02 |
| Power stage | 6 × EPC23102 (eGaN half-bridge with integrated driver) |
| Current sense | 6 × INA240A1D across 2 mΩ 1206 shunts |
| CAN transceivers | 3 × TJA1051T/3 |
| Signal switches | 12 × 74LVC1G66 (current / voltage filter enables) |
| FET temperature | 6 × NCP15XH103 NTC (10 kΩ @ 25 °C, one per phase) |
| Logic supply | LMR16006XDDCR: Vdrive → `+5V` → `+3V3` |
| Bus protection | 20 A fuse, SMAJ58A TVS |
| Bulk storage | 8 × 100 µF 80 V, 12 × 1 µF 100 V, 6 × 4.7 µF 100 V |
| Input connector | AMASS XT60IPW-M |
| Motor connectors | 2 × AMASS MR30PW-M |
| Hall / COMM | JST PH 6-pin (×2) / 8-pin (×2) |
| USB | 3 × USB-C 16-pin |
| Debug | 2 × Tag-Connect TC2030 SWD |
| Buttons | 2 × KMR211NGLFS |
| EDA | KiCad |

---

## Acknowledgements / Based On

- [**VESC** by Benjamin Vedder](https://github.com/vedderb/bldc) — firmware target, VESC Tool compatibility and the [VESC 75/300](https://vesc-project.com/) hardware reference
- [**EPC23108 / EPC23102 ePower™ Stage ICs** by EPC](https://epc-co.com/epc/products/gan-fets-and-ics/epc23108) — power stage, and the [EPC91128 3-phase BLDC inverter reference design](https://epc-co.com/epc/portals/0/epc/documents/guides/EPC91128-EPC91131_qsg.pdf)

---

## License

Hardware design files are licensed under the **CERN Open Hardware Licence Version 2 – Strongly Reciprocal (CERN-OHL-S v2.0)**.

See [`LICENSE`](./LICENSE) for the full text, or visit [ohwr.org/cern_ohl_s_v2](https://ohwr.org/cern_ohl_s_v2.txt).

> In short: you are free to use, study, modify, and distribute this design, provided that any derivatives are released under the same licence and source files are made available.
