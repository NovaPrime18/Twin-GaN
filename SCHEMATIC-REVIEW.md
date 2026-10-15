# Twin-GaN-VESC — schematic review

Scope: **schematic only** (board not reviewed, as requested).
KiCad 10.0.6 · root `Twin-GaN-VESC.kicad_sch` + 5 child sheets in 11 sheet instances · **318 components** (305 with an LCSC number).
Automated ERC as-shipped: **33 errors, 97 warnings**.

Everything below was verified against the resolved netlist (`kicad-cli sch export netlist`), KiCad's ERC report, and the **live** JLCPCB/LCSC parts API (not just the local cache).

---

## 1. Critical

### 1.1 The low-voltage supply has no power input — +5 V and +3 V3 have no source
`U15` and `U16` (LMR16006XDDCR) sit in `LV-Supply.kicad_sch`, and their VIN pins are on nets that contain **only their own decoupling capacitors**:

| Net | Nodes |
|---|---|
| `Net-(U15-IN)` | C56.1, C61.1, C62.1, **U15.5 (IN)** |
| `Net-(U16-IN)` | C86.1, C87.1, C88.1, **U16.5 (IN)** |

There is nothing else: the wire runs stop at x = 134.62 mm and x = 137.16 mm and go nowhere.

`LV-Supply` is the **only sheet with zero hierarchical pins** (all 10 other sheet instances have pins), it contains **no global label**, no power symbol other than GND/+3V3/+5V, and no input connector. Its only labels are the three internal ones (`3V3_SW`, `3V3_FB`, `3V3_CB`).

ERC cannot see this because the `LMR16006XDDCR` symbol types **every pin as `passive`** — including `IN` — so no `power_pin_not_driven` is raised.

Consequence: as drawn, nothing generates +5 V or +3 V3, so the whole logic side (both STM32s, the ESP32-C3, all CAN transceivers, the INA240s) is unpowered.

**Fix:** put a `Vdrive` power symbol on both input nets (or add an input sheet pin on `LV-Supply` and wire it to the `Vdrive` rail on the root). The input caps are already 100 V and the LMR16006 is a 4–60 V part, so `Vdrive` is clearly the intended source.

### 1.2 `C15742` (STM32F405RGT6, U1 and U4) is out of stock at JLCPCB right now
Live query of the JLCPCB parts API today returns `stockCount = 0`. The local `.konnect` cache is from 2026-09-03 and still claimed 5 339 — this is exactly the staleness trap. The part number is valid and the assignment is correct (U1/U4 = STM32F405RGTx, LQFP-64 ↔ LCSC `STM32F405RGT6`, LQFP-64(10x10)); it simply cannot be placed right now.

### 1.3 Two footprint libraries used by the schematic do not exist
| Missing library | Symbol | Used by |
|---|---|---|
| `PCM_JLCPCB` | `TYPE-C-SMD_HX-TYPE-C-16PIN` | **J7, J12, J13** (all three USB-C) |
| `PCM_JLCPCB` | `D_SMA` | **D27** (SMAJ58A TVS) |

These are hard ERC errors against a real board (`footprint_link_issues`). KiCad can still export the netlist because symbols are embedded, but the PCB cannot be built for these five parts until the footprints are supplied or the footprints are re-pointed at standard KiCad ones (`Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12` etc.).

---

## 2. High

### 2.1 All three voltage filters have their input and output shorted — in **both** channel instances
ERC: `Both Volt_U_In and Volt_U_Out are attached to the same items` (×3 for `/Filters/`, and the same defect exists in `/Filters1/` — the netlist has **no** `Volt_*_Out` net at all).

Measured on the sheet: `Volt_U_In` (128.27,166.37), `Volt_U_Out` (120.65,166.37) and `C47.1` all land on x = 127.0 with a junction — one node.

Compare with the current channels, which are correct: `Curr_U_In` → R67 → `Curr_U_Out` (+C49, +the enable switch). So the voltage sheet draws the divider tap straight through with no series element between In and Out; the sheet's own input and output pins are the same netlist node.

Netlist evidence: `/Filters/Volt_U_In` = R39.2, R40.1, C47.1, U1.14 and there is no `/Filters/Volt_U_Out`.

**Fix:** put `Volt_U_Out` on the ADC node and `Volt_U_In` on the phase side of R39 (i.e. move one hierarchical label), or accept that the "filter" is only the 56k/56k divider and rename the two pins.

### 2.2 CAN never leaves the board, and its termination is 220 Ω
`/CAN/CANH` and `/CAN/CANL` contain exactly:

```
/CAN/CANH : R41.1, U7.7,  U31.7, U32.7      (the 3 transceivers + one resistor)
/CAN/CANL : R41.2, U7.6,  U31.6, U32.6
```

No connector pin carries CANH/CANL — the two "COMM" headers J5/J10 are fully used (1 +5V, 2 +3V3, 3 GND, 4 SCK, 5 SDA/NSS, 6 SCL/MOSI, 7 MISO, 8 ADC-15). So the CAN bus is internal-only between ESP32-C3, MCU1 and MCU2.

Also, `R41` is **220 Ω** across CANH/CANL. Standard CAN termination is 120 Ω (or 2 × 60 Ω split with a cap) — 220 Ω gives roughly half the correct load. With three transceivers on a stubless internal bus and no external termination point, that is worth re-deriving deliberately.

### 2.3 `STB`/`EN` (pin 3) floating on all six EPC23102 GaN stages
U2, U5, U6, U18, U26, U27 pin 3 is `unconnected-(…-ENb-Pad3)` — six pins. The EPC23102 datasheet names pin 3 `STB`/`EN`: *"Internal VDD will be disabled when STB is pulled up… Internal pull-down resistor is connected between STB and AGND, thereby VDD will follow VDRV with STB connected to AGND by default."* So the internal pull-down will probably keep it enabled, but leaving a gate-driver enable floating on a 100 V power stage is not acceptable practice — tie it to AGND explicitly (EPC's own reference designs do).

Note ERC reports this only for the `/Phase/` instance (3 pins); the `/Phase1/` instance (U5, U26, U27) has the identical defect but ERC under-reports repeated sheet instances.

### 2.4 `~SHDN` (pin 4) floating on both bucks — U15, U16
ERC errors `pin_not_connected` ×2 in `/LV-Supply/`. Active-low shutdown on the LMR16006 must be tied to a defined level (usually VIN for always-on, or driven). Currently undefined.

---

## 3. Medium

| # | Item | Detail |
|---|---|---|
| 3.1 | **Main fuse rating** | `F1` = 20 A / 250 V slow-blow on the single `Vdrive` rail feeding six 100 V EPC23102 half-bridges, from an XT60 input and out to MR30 (30 A) motor connectors. 20 A looks undersized for a twin 65 A-class inverter — please re-derive. |
| 3.2 | **F1 package ≠ footprint** | LCSC `C49269483` `BSMD2410C-2200T` is a **2410** (6.1 × 2.6 mm) fuse; footprint is `Fuse:Fuse_2512_6332Metric` (6.3 × 3.2 mm). KiCad has no 2410 land, but the mismatch should be deliberate and documented, not accidental. |
| 3.3 | **PTC fuses on resistor footprints** | `F2`, `F3`, `F4` (SMD0805-050 0.5 A PTC) use `Resistor_SMD:R_0805_2012Metric`. Use `Fuse:Fuse_0805_2012Metric` — same land, correct silkscreen/DRC class. |
| 3.4 | **Bulk cap rating vs TVS clamp** | `C110–C118` are 100 µF **80 V**, but the bus TVS `D27` (SMAJ58A) has Vbr ≈ 71.2 V and a clamp of **93.6 V**. During a surge the caps are the first thing over 80 V, before the TVS clamps. Either raise the cap rating or tighten the clamp. |
| 3.5 | **DC-bias derating on the bus** | The 12 × 1 µF 100 V **0805 X7R** on `Vdrive` will lose a large fraction of their capacitance under ~58 V DC bias. If the intent is real bulk, use larger case sizes / higher voltage. |
| 3.6 | **BOM data inconsistent** | Only 305/318 parts have an `LCSC` number, 21 have `Manufacturer Part Number`, 34 have `Manufacturer`, 94 have a `Datasheet` link. On top of that, **two generations of field names are in use**: 26 parts carry an obsolete `JLC` property alongside `LCSC`, and 13 parts carry a `Part`/`Stock`/`Price`/`Process`/`Minimum Qty`/`Attrition Qty`/`Class`/`Category` set. Pick one column set (LCSC + MPN + Manufacturer + Datasheet) before generating the CP-L. |
| 3.7 | **D11–D29 metadata contradicts the part** | All twelve DSK310 diodes carry `Part = SS28` and are drawn as library symbol `PCM_JLCPCB-Diodes:Schottky,SS28`. SS28 is a different diode (2 A / 80 V) than the DSK310 that will actually be ordered (100 V / 3 A). The `Value` is correct (`DSK310`), the rest is stale — an assembler reading `Part` would source the wrong diode. |
| 3.8 | **Value text vs part** | `C307418` value says `2.2uF 16V` but the LCSC part is **25 V** (12 refs: C100–C102, C114, C119, C120, C128–C133). `C25897` value says `50k`, part is 49.9 kΩ. `C2934560` value omits the `-N4` flash variant. |
| 3.9 | **No `PWR_FLAG` anywhere** | Zero PWR_FLAG symbols in any sheet → ERC raises `power_pin_not_driven` on GND, +3V3, +5V, Vdrive and VDDA. Spurious, but it hides real problems in the 33-error list. |
| 3.10 | **No test points on any rail** | +3V3, +5V, Vdrive, GND all lack a test point. |
| 3.11 | **Unused pins without no-connect flags** | 33 ERC errors. `J2.6`/`J8.6`; `U1`/`U4` PC13/14/15, PB2, PB3, PB4, PB6, PB11, PB12, PA7, PA15, PC10/11/12; `U8` IO3/4/5/6/7/10, IO20/RXD, IO21/TXD; `J7`/`J12`/`J13` SBU1/SBU2. Only `MCU.kicad_sch` uses any NC flags (6) — the other sheets use none. |
| 3.12 | **PB2 = BOOT1 floating** on both STM32F405 (pin 28). ST requires BOOT1 to be held low during reset; it is not broken out to anything. |
| 3.13 | **Duplicate part numbers for the same value** | 1 kΩ 0402: `C11702` (Basic, ×10) **and** `C106235` (Extended, ×2, R77/R95). 10 kΩ 0402: `C25744` (Basic, ×11) **and** `C2906861` (Extended, ×2, R92/R94). Consolidating removes 2 Extended part types (≈ 2 × $3 setup) and 2 feeders. |
| 3.14 | **Low-stock parts** | `C11626` 54.9 kΩ — 488 pcs (cache said 17 751: it is falling). `C1346458` INA240A1D — 1 736 pcs at **$1.77** each ×6. `C221676` KMR211NGLFS — 2 542. `C495548` JST B8B-PH — 2 457. |
| 3.15 | **Voltage-filter ADC source impedance** | With `EN_V` low, `C47` is disconnected from ground, so the STM32 ADC sees the bare 28 kΩ (56k‖56k) divider. That is at/over the STM32F4 guidance for source impedance without an external cap — verify against the sampling time you configure. |
| 3.16 | **13 parts have no LCSC number at all** (they will not be placed by JLCPCB) | The six **EPC23102 GaN stages** (`U2`, `U5`, `U6`, `U18`, `U26`, `U27`) — the heart of the board — plus the three AMASS power connectors (`J1`/`J11` MR30PW-M, `J3` XT60IPW-M), the two Tag-Connect SWD headers (`J2`, `J8`) and the two solder jumpers `JP1`/`JP2`. The EPC23102 is not a JLCPCB-stocked part (verify at EPC/Mouser/DigiKey and set an MPN + supplier field), the connectors and Tag-Connects are normally hand-soldered and should be marked accordingly, and the solder jumpers need a part chosen. |

---

## 4. Low / cosmetic

- `D22`, `D24`, `D25` have value `LED` while `D1`, `D5` have value `Red` — all five are the same part (`C2286`, red 0603). Make the value text uniform.
- ERC `multiple_net_names`: local `EN_C` and `EN_V` sit on the same wires as the hierarchical `Enable Curr Filters` / `Enable Voltage Filters` (benign — the net just takes the local name).
- ERC `lib_symbol_mismatch` on `Device:C_Small` for ~80 capacitors (the schematic's embedded copy was edited, e.g. footprints changed). Harmless but noisy.
- 5 symbol libraries are unresolvable: `0_passives`, `0_PD240W`, `EPC_FETs`, `PCM_JLCPCB-Diodes`, `PCM_JLCPCB-Extended`. Symbols are embedded so the design ships, but *Update Symbols from Library* is dead.
- Title block is `2026-10-15`, rev `R1` on every sheet with no revision history.

---

## 5. What I checked and found **clean**

- **All 50 distinct LCSC numbers exist** in the live JLCPCB catalogue — 50/50 queried through the JLCPCB parts API (`https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList`), not the 6-week-old local cache.
- **Every R / C / L value matches its LCSC part** (automated normalisation of `22`, `2k2`, `1u`, `100n`, `22uH`, … against the part's real value) — zero mismatches.
- **Every designator prefix matches its part category** (the only reports are R74–R76/R81–R83, which are legitimately NTC thermistors on `R` designators).
- No duplicate or unannotated reference designators (318/318 unique).
- `validate_sheet_pins`: 0 issues — every hierarchical label has a matching sheet pin and vice versa.
- No shorted nets, no single-pin nets, no orphan/dangling wire ends on the root beyond `J2.6`/`J8.6`.
- Root-sheet sheet-pin wiring is correct pin-for-pin: `H_U↔HIN_U`, `L_*↔LIN_*`, `Curr_*↔Curr_*_In`, `Volt_*↔Volt_*_In`, `Temp *↔FET_Temp_*`, `Current *↔Curr_*_Out`, `Voltage *↔Volt_*_Out`, `CAN_TX/RX↔TX/RX`, and `CANH/CANL` common across the three transceivers.
- The two channels are electrically identical (U2/U3/U9/U18/U19/R97–R99 vs U5/U26/U27/U28/U29/U30/R100–R102, D11–D21 vs D12–D29, C18–C24 vs C97–C99 …).
- `EPC23102` symbol pin numbers match the [datasheet](https://epc-co.com/epc/portals/0/epc/documents/datasheets/EPC23102_datasheet.pdf) 1:1, and the surrounding network is right: `RDRV`→R52/R54/R56/R66/R69/R70 to VDRV, `RBOOT`→R53/R55/R57/R71/R87/R88 to VBOOT, `VBOOT` bootstrap caps to `VPHASE`, `SW`+`VPHASE` Kelvin-tied, `VIN` on Vdrive, `VDD` and `VDRV` decoupled.
- `INA240` references are correct: `REF1`=GND, `REF2`=+3V3 → 1.65 V mid-supply for bidirectional current, shunt in the phase leg with `IN+` on the bridge side (positive current = positive output).
- **USB D+/D− polarity is correct on all three ports**, including the ESP32-C3 native USB (D+ → IO19, D− → IO18 — pins 14/13).
- USB-C CC1/CC2 have 5.1 kΩ pulldowns (UFP), D+/D− A6/B6 and A7/B7 strapped, VBUS → 0.5 A PTC → ferrite → diode → +5 V on each port.
- ESP32-C3 support circuit is right: EN = 10 k + 1 µF, IO9 boot button, IO8 and IO2 10 k pulls.
- STM32 support: VDDA from +3V3 through R10 (4.7 Ω) + 4.7 µF/100 nF, VCAP1/VCAP2 caps, NRST 10 k/100 nF, BOOT0 tied to GND, 8 MHz crystal with 15 pF load caps (≈12 pF effective → matches the 12 pF crystal).
- INA240 VDDA/PWR_FLAG false positives are exactly that — VDDA *is* fed through R10.

---

## Appendix — live LCSC verification of all 50 part numbers

| LCSC | Qty | Mfr P/N | Pkg | JLCPCB | Live stock | Verdict |
|---|---:|---|---|---|---:|---|
| C307331 | 49 | CL05B104KB54PNC | 0402 | Basic | 24,977,453 | exists / value+package match |
| C25092 | 20 | 0402WGF220JTCE | 0402 | Basic | 4,080,256 | exists / value+package match |
| C5370002 | 18 | CC0805KKX7R0BB105 | 0805 | Extended | 505,113 | exists / value match (value text inconsistent) |
| C20539421 | 16 | TCC0402X5R225K100AT | 0402 | Extended | 1,214,658 | exists / value+package match |
| C97489 | 12 | 74LVC1G66GW,125 | SOT-353 | Extended | 6,458 | exists / value+package match |
| C307418 | 12 | CL05A225KA5NUNC | 0402 | Extended | 741,672 | exists / 25 V part, value text says 16 V |
| C28646289 | 12 | DSK310 | SOD-123FL | Extended | 301,669 | exists / match (symbol + Part field say "SS28") |
| C25077 | 12 | 0402WGF100JTCE | 0402 | Basic | 3,980,842 | exists / value+package match |
| C25744 | 11 | 0402WGF1002TCE | 0402 | Basic | 21,549,319 | exists / value+package match |
| C11702 | 10 | 0402WGF1001TCE | 0402 | Basic | 14,414,111 | exists / value+package match |
| C487410 | 8 | VKME1001K101MV | SMD,D10xL10mm | Extended | 5,547 | exists / value+package match |
| C23206 | 7 | 0603WAF5602T5E | 0603 | Basic | 875,357 | exists / value+package match |
| C25879 | 7 | 0402WGF2201TCE | 0402 | Basic | 2,038,379 | exists / value+package match |
| C25905 | 6 | 0402WGF5101TCE | 0402 | Basic | 5,303,820 | exists / value+package match |
| C114405 | 6 | CC0402KRX7R9BB153 | 0402 | Extended | 557,251 | exists / value+package match |
| C1523 | 6 | 0402B102K500NT | 0402 | Basic | 3,110,898 | exists / value+package match |
| C3039694 | 6 | CL21B106KAYQNNE | 0805 | Extended | 277,860 | exists / value+package match |
| C22367839 | 6 | HHV1206R7475K101NSPJ | 1206 | Extended | 470,502 | exists / value+package match |
| C77131 | 6 | NCP15XH103F03RC | 0402 | Extended | 308,685 | exists / value+package match |
| C601094 | 6 | HoLR1206-1W-2mR-1%-75ppm | 1206 | Extended | 6,471 | exists / value+package match |
| C1346458 | 6 | INA240A1D | SOIC-8 | Extended | 1,736 | exists / match — low stock |
| C2286 | 5 | KT-0603R | 0603 | Basic | 7,837,213 | exists / value+package match |
| C440198 | 5 | GRM21BR61H106KE43L | 0805 | Basic | 1,202,154 | exists / value+package match |
| C1548 | 4 | 0402CG150J500NT | 0402 | Basic | 1,210,282 | exists / value+package match |
| C459527 | 3 | BAV16W-7-F | SOD-123 | Extended | 6,103 | exists / value+package match |
| C2833485 | 3 | SMD0805-050-16V | 0805 | Extended | 11,760 | exists / PTC on a resistor footprint |
| C76884 | 3 | BLM15AG601SN1D | 0402 | Extended | 1,294,327 | exists / value+package match |
| C2927039 | 3 | USB-TYPE-C-019 | SMD | Extended | 171,431 | exists / value+package match |
| C2875699 | 3 | TJA1051TK/3/1J | HVSON-8-EP(3x3) | Extended | 22,642 | exists / value+package match |
| C84267 | 2 | NCD0603G1 | 0603 | Extended | 875,847 | exists / value+package match |
| C471518 | 2 | B6B-PH-SM4-TB(LF)(SN) | SMD,P=2mm | Extended | 9,459 | exists / value+package match |
| C495548 | 2 | B8B-PH-SM4-TB(LF)(SN) | SMD,P=2mm | Extended | 2,457 | exists / match — low stock |
| C25121 | 2 | 0402WGF470KTCE | 0402 | Extended | 19,647 | exists / value+package match |
| C15742 | 2 | STM32F405RGT6 | LQFP-64(10x10) | Extended | 0 | **OUT OF STOCK (0)** |
| C2682775 | 2 | X32258MOB4SI | SMD3225-4P | Extended | 94,737 | exists / value+package match |
| C221676 | 2 | KMR211NGLFS | SMD | Extended | 2,542 | exists / match — low stock |
| C15725 | 2 | CL10B104KC8NNNC | 0603 | Extended | 192,675 | exists / value+package match |
| C235757 | 2 | MBR1H100SFT3G | SOD-123FL | Extended | 12,139 | exists / value+package match |
| C83472 | 2 | SWPA4030S220MT | SMD,4x4mm | Extended | 44,030 | exists / value+package match |
| C106235 | 2 | RC0402FR-071KL | 0402 | Extended | 1,728,131 | exists / value+package match |
| C2906861 | 2 | FRC0402F1002TS | 0402 | Extended | 17,095,589 | exists / value+package match |
| C87080 | 2 | LMR16006XDDCR | SOT-6 | Extended | 51,924 | exists / value+package match |
| C19077554 | 1 | SMAJ58A | DO-214AC(SMA) | Extended | 48,864 | exists / value+package match |
| C49269483 | 1 | BSMD2410C-2200T | 2410 | Extended | 23,340 | exists / package 2410 ≠ footprint 2512 |
| C22962 | 1 | 0603WAF2200T5E | 0603 | Basic | 2,031,183 | exists / value+package match |
| C25897 | 1 | 0402WGF4992TCE | 0402 | Extended | 16,583 | exists / 49.9 kΩ (value text says 50k) |
| C52923 | 1 | CL05A105KA5NQNC | 0402 | Basic | 7,565,565 | exists / value+package match |
| C2934560 | 1 | ESP32-C3-WROOM-02-N4 | SMD,20x18mm | Extended | 5,776 | exists / N4 variant (value omits -N4) |
| C138003 | 1 | RC0402FR-0733KL | 0402 | Extended | 812,266 | exists / value+package match |
| C11626 | 1 | 0402WGF5492TCE | 0402 | Extended | 488 | exists / match — low stock |

*Live stock read from the JLCPCB parts API. Library type: Basic parts have no setup fee, Extended parts do (≈ $3/type at JLCPCB; 36 extended types here ≈ $108). Estimated part cost for one board at 10+ pricing: ≈ **$28.45** plus ≈ $108 extended-part setup; two Extended part types (3.13) are avoidable.*

Machine-readable evidence is in `.review/`: `erc.json` (raw ERC), `live_verify.json` (live API responses), `lcsc_verify.json` (cache-vs-schematic table), `comps.json` (resolved netlist components), `net.xml` (full netlist).
