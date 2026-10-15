# Twin-GaN-VESC — pre-order board review

Reviewed: 2026-10-15, KiCad 10.0.6 · root `Twin-GaN-VESC.kicad_sch` + 6 child sheets in 12 sheet
instances · 322 placed parts · board 99.0 × 99.0 mm, 4 layer, 1.6 mm.
Method: fresh netlist export, ERC, PCB DRC, and byte-level inspection of the *shipped*
`production/Twin-GaN-VESC.zip` Gerbers.

**Verdict: do NOT order yet.** The copper/routing side is genuinely clean, but the production
package has one hard manufacturing defect that would make every GaN power stage unsolderable.

> **Author's decisions (confirmed by the board owner after this review):**
> - `F1` = 20 A is deliberate — the design is intended to run **under 20 A** battery current.
> - CAN is intentionally internal-only; the 220 Ω termination is accepted.
> - The fab package (BOM/CPL/Gerbers) is deliberately left as-is for now.
> - **The GaN solder-mask defect below is deliberately still unfixed.** It is a physical
>   blocker, not a preference — see "Blocker 1" before placing the order.

---

## Blocker 1 — all six GaN stages have no solder mask and no solder paste

`U2, U5, U6, U18, U26, U27` (the six EPC23102 half-bridges) use footprint
`Thommys-Parts:D0727`. **Every one of its 13 pads** carries:

```
(solder_mask_margin -1)
(solder_paste_margin -1)
```

Those are in the footprint's own units, i.e. **−1 mm**, so the aperture KiCad computes is
`pad_size − 2 mm` — negative for every pad on the part. KiCad therefore emits no aperture at all.

Evidence, in order of strength:

| Check | Result |
|---|---|
| DRC | 120 warnings, "no solder mask will be generated" / "no solder paste mask will be generated", 10 pad instances × 6 parts × 2 (mask+paste) |
| Board file | 78 pads across 6 parts with a negative mask margin, 78 with a negative paste margin — this footprint is the **only** one on the board with negative margins |
| **Shipped Gerber** `F_Mask.gts` | **0 of U2's 13 pad centres carry a `D03` flash** |
| **Shipped Gerber** `F_Paste.gtp` | **0 of U2's 13 pad centres carry a `D03` flash** |
| Control | 18 other flashes exist in the same 10 × 9 mm box around U2, including one at an identical X coordinate — so the detection is sound, not a mapping artefact |

Consequence: the copper comes back covered in soldermask with no stencil openings. The GaN
stages cannot be soldered — by JLCPCB or by hand. As ordered, this is a scrap board.

Fix: set `solder_mask_margin` / `solder_paste_margin` to `0` (or a normal positive expansion such
as `0.05`) in `Thommys-Parts.pretty/D0727.kicad_mod` — the `D0727m` and `D0727u` variants in the
same directory have the identical defect (13 pads each) — then *Update Footprints from Library*
on the board, re-run DRC (expect those 120 warnings to disappear) and re-export the fab package.

---

## Blocker 2 — the CPL/BOM pair will not upload to JLCPCB cleanly

| Artefact | Count | Problem |
|---|---|---|
| `bom.csv` | 314 parts / 55 lines | 4 lines have **no LCSC number**: 6 × EPC23102, 2 × MR30 (J1, J11), 1 × XT60 (J3) |
| `positions.csv` | 320 rows | includes **H1–H4** (mounting holes) and **JP1/JP2** (solder jumpers), which are *not* in the BOM |
| mismatch | 8 designators | on the board but absent from the BOM: H1, H2, H3, H4, J2, J8, JP1, JP2 |

JLCPCB's assembly upload matches BOM lines to CPL designators; extra CPL entries and CPL rows
with no part number both trip it. Mounting holes and the two solder jumpers should be dropped
from the CPL, and the 6 GaN parts plus the 3 power connectors need a decision: give them a part
number, or strip them from the CPL and mark them hand-place.

(`J2`/`J8`, the two Tag-Connect SWD headers, are already correctly flagged
`exclude_from_pos_files exclude_from_bom` — do the same for JP1/JP2 and the holes.)

---

## The good news — routing and netlist are clean

- **DRC `unconnected_items = 0`** — every net is fully routed.
- **DRC `schematic_parity = 0`** — the board matches the current schematic.
- **No clearance, short, or track-width violations.** Min track is 0.20 mm (mostly 0.25 mm,
  power up to 2.0 mm) against a 0.15 mm rule and JLCPCB's 0.09 mm 4-layer limit. All 1342 vias are
  0.5 / 0.3 mm, which JLCPCB handles.
- 69 copper pours, board outline is a clean closed 99 × 99 mm rounded rectangle (3 mm corners).
- No duplicate or unannotated designators (the only `REF**` entries are the two silkscreen logos,
  correctly `board_only` / `exclude_from_bom`).
- Drill file tool list is sane: PTH 0.2 / 0.3 / 0.5 / 0.6 / 1.0 / 1.9 / 2.7 mm, NPTH 0.6 / 0.991 / 2.7 mm.

**Power tree is correct and complete** (this was the earlier review's critical finding, now fixed):
`J3 XT60 → F1 → Vdrive`, then `U16` (LMR16006) bucks Vdrive down to `+5V`, then `U15` bucks `+5V`
to `+3V3`. Feedback dividers check out against the LMR16006's 0.765 V reference:
`R93/R92 = 54.9k/10k → 4.97 V` and `R86/R94 = 33k/10k → 3.29 V`.

**Battery polarity is right.** In the official XT60IPW-M footprint the `−` silkscreen marker sits at
x = −2.8 (pad 1) and the `+` at x = 9.5 (pad 2). On this board pad 1 → GND and pad 2 → F1 → Vdrive.
Correct.

**Floating enables are benign** (verified against both datasheets):
- `U15/U16` SHDN pin 4 floats — LMR16006: *"Internal pull-up current source… Float to enable."* → the
  bucks come up.
- `U2/U5/U6/U18/U26/U27` STB pin 3 floats — EPC23102: *"Internal pull-down resistor… thereby VDD will
  follow VDRV with STB connected to AGND by default."* → the stages come up enabled.
  (EPC explicitly warns *do not* tie STB to VDD.) Still worth tying both off deliberately.

---

## Real issues, in priority order

### 1. Main fuse is 20 A — **CONFIRMED INTENTIONAL**
`F1` is a single 20 A fuse on the only `Vdrive` input, feeding six half-bridges out to two 30 A-rated
MR30 motor connectors, from a 60 A-rated XT60. The owner confirms the design targets **under 20 A**
battery current, so the rating is deliberate. Closing this item.
(Check still worth making: `F1`'s LCSC part `C49269483` is a **2410** body on a **2512** land — confirm
it sits the pads.)

### 2. Bulk-cap rating is below the TVS clamp
`C110–C118` are 100 µF **80 V** (confirmed: LCSC `C487410` = Ymin VKME1001K101MV, 100 µF 80 V), but the
bus TVS `D27` (SMAJ58A) clamps at up to **93.6 V**. A surge lets the TVS pass 93.6 V into 80 V caps.
The same rail also feeds `U16` (LMR16006, **60 V** abs max) directly, so the TVS is not protecting the
logic supply either. Raise the caps to 100 V and/or add a series element ahead of `U16`.

### 3. Shunt power rating — acceptable at the stated current, but with no margin
`R97–R102` are 2 mΩ in 1206, rated 1 W. `P = I²R` gives 0.32 W at 12.6 A, **0.8 W at 20 A** (80 % of
rating), and 1 W at 22.4 A. At the confirmed <20 A battery current this is fine, but note that phase
current is not battery current — under heavy throttle with low battery voltage the phase current
can exceed the battery current. If you want margin, treat ~15 A continuous as the comfortable limit.

### 4. CAN never leaves the board, and its termination is 220 Ω — **CONFIRMED INTENTIONAL**
`/CAN/CANH` and `/CAN/CANL` contain exactly the three TJA1051 transceivers (`U7`, `U31`, `U32`) and
`R41` = **220 Ω**. No connector pin anywhere carries CANH/CANL, so the bus is internal only
(ESP32 + both STM32s). The owner confirms this is intended and accepts the 220 Ω termination.
Closing this item.

### 5. Voltage-filter sheet pins are shorted to each other (×6)
`Volt_U/V/W_In` and `Volt_U/V/W_Out` land on the same node in **both** `Filters` instances — the
netlist has no `Volt_*_Out` net at all. **This is cosmetic, not a wiring bug**: the ADC still sees
the divider (`R39` 56k → node, `R40` 2k2 → GND, `C47` 100 nF), so the channel works. The
`Volt_*_Out` hierarchical pins are simply redundant and generate 6 ERC warnings. Collapse the pin
pair (or move one label) to silence it.

### 6. Board setup min hole (0.30 mm) blocks 12 real 0.20 mm holes
`U8` (ESP32 module) has 12 thermal vias at 0.20 mm; `min_through_hole_diameter` is 0.30 mm →
12 DRC errors. JLCPCB's 4-layer minimum is 0.20 mm, so the board is manufacturable as drawn; set the
board rule to 0.20 to clear the errors.

### 7. Missing footprint library `PCM_JLCPCB`
`J7`, `J12`, `J13` (USB-C) and `D27` (SMAJ58A) reference a footprint library that is not registered.
The board itself is fine (footprints are embedded and placed), so this does not block fabrication —
but it breaks *Update Footprints from Library* and leaves the schematic unable to resolve 5 symbol
libraries (`0_passives`, `0_PD240W`, `EPC_FETs`, `PCM_JLCPCB-Diodes`, `PCM_JLCPCB-Extended`).

### 8. Cosmetic / tidy-up
- 30 × `starved_thermal`: GND pads with a single thermal spoke (`min_resolved_spokes = 2`).
- 15 × silkscreen clipped by the board edge — J3, J4, J5, J9, J10, J11 reference text runs off the
  outline. 61 × silkscreen over copper, 4 × silk overlap.
- Courtyard overlaps: `H3` and `H4` (M2.5 holes) overlap `U8`'s courtyard, and `H4` also overlaps
  `J11`. Check mechanically that the screws clear the ESP32 module and the MR30.
- 33 ERC `pin_not_connected` errors — unused pins with no NC flag: `J2.6`, `J8.6`,
  `J7/J12/J13` SBU1/SBU2, `U1/U4` PA7/PB3/PB4/PB6/PB11/PC10/PC11/PC12, `U8` IO3–IO7/IO10/IO20/IO21.
  Add NC flags to clean up the ERC report.
- `U1/U4` PB2 (BOOT1) is marked no-connect. ST recommends BOOT1 be held low; a 10k to GND is safer.
- `J3` uses symbol `Conn_01x04` against the 3-pad XT60 footprint, so symbol pin 4 has no pad. It is a
  GND pin on a net that already has two, so it is harmless — but it is a latent netlist/board
  inconsistency waiting to confuse a future *Update PCB from Schematic*.
- Title block is still `rev R1` / date 2026-10-15; the Gerber header carries `rev?`.
- No test points on any rail.
- 40 of 322 parts have no MPN; two generations of BOM field names are still mixed (`JLC` vs `LCSC`,
  plus a `Part`/`Stock`/`Price` set). `D11–D29` still carry stale `Part = SS28` metadata while the
  real part is a DSK310.

---

## Previously flagged, now resolved

- LV supply had no source — **fixed**: the Vdrive → 5 V → 3.3 V chain is complete and correct.
- `C15742` STM32F405RGT6 out of stock — **back in stock** (5339 pcs at time of writing).
- Missing footprints on J7/J12/J13/D27 — the board now carries them; only the library registration
  is still missing (item 7).
- The 56k/56k voltage divider is actually 56k/2k2, so source impedance is ~2.1 kΩ, comfortably inside
  STM32F4 guidance.

---

## Fix list before ordering

1. **Set both solder margins to 0 in `D0727.kicad_mod` (and `D0727m`/`D0727u`), update footprints from
   library, re-run DRC, re-export Gerbers.** — **still open, deliberately deferred by the owner.**
   This is the one that matters; until it is done the board cannot be assembled.
2. Rebuild the CPL without H1–H4 and JP1/JP2, and decide the assembly route for the 6 GaN stages and
   the 3 power connectors. — package deliberately left as-is for now.
3. Settle the 80 V caps vs the 93.6 V TVS clamp (and `U16`'s 60 V abs max on `Vdrive`). — still open,
   independent of the current decision.
4. Set `min_through_hole_diameter = 0.2 mm`.
5. ~~Decide whether CAN needs a connector, and whether 220 Ω is intended.~~ — confirmed intentional.
6. ~~Re-derive `F1`.~~ — confirmed intentional at <20 A.

Machine-readable evidence for this review: `.review/net-now.xml` (fresh netlist),
`.review/erc-all.json`, `.review/drc2.json`, `.review/gb/` (unpacked shipped Gerbers),
`.review/parse_net.py` (the netlist query tool used above).
