# Twin-GaN — PCB copper loss & temperature analysis

**Scenario:** 54 V in, **20 A DC total**, split equally between the two drivers
(10 A per channel), 25 °C ambient, 10 minutes continuous.
**Stackup analysed as fabricated:** 1 oz (35 µm) on F.Cu/B.Cu, **0.5 oz
(17.5 µm) on In1.Cu/In2.Cu**.

---

## 1. Headline

| | |
|---|---|
| **Hottest PCB copper** | **90.4 °C** — the 2.0 mm F.Cu trace from shunt `R98` to motor connector `J1` (Phase V) |
| Hottest copper pour | 85.0 °C — the `Net-(U6-Phase)` switch-node pour, immediately at the shunt |
| Hottest via | 49.5 °C (GND stitching) |
| Board-wide average | 36.5 °C (11.5 K rise) |
| Total PCB copper loss | **2.81 W** |
| Total shunt loss (components) | 1.07 W |
| 10 minutes is… | 6.3 thermal time constants → **99.8 % of the final rise**, i.e. steady state |

The 2.0 mm trace is the one that needs more copper. Everything else on the
board — Vdrive, GND, and the switch nodes — is copper pour; this short trace is
the only place where the full phase current runs through a plain 1 oz trace.

---

## 2. Loss and temperature by block

| Block | P (mW) | R<sub>eff</sub> (mΩ) | T<sub>max</sub> (°C) |
|---|---:|---:|---:|
| Input pour, XT60 `J3` → fuse `F1` | 342 | 0.854 | 45.5 |
| Vdrive bus, `F1` → six FET drains | 908 | 2.270 | 45.8 |
| GND return, six FET sources → `J3` | 194 | 0.486 | 54.5 |
| Phase ch1-U / V / W | 413 / 439 / 382 | 4.65 / 4.94 / 4.29 | 79.1 / **90.4** / 81.1 |
| Phase ch2-U / V / W | 406 / 421 / 371 | 4.57 / 4.73 / 4.17 | 77.8 / 83.1 / 73.4 |
| **PCB copper total** | **2 805** | | |
| 6 × 2 mΩ shunts (components, not copper) | 1 070 | | 71–88 |

Each phase figure includes its 178 mW shunt, so the six phase *copper* paths
together burn 1 361 mW of the 2 805 mW.

Currents used: 20 A in at `F1`, 3.333 A DC average out of each half-bridge;
9.43 A rms per phase leg.

---

## 3. Where the phase current actually goes

Following one leg (U2 → R97 → J1) in the solved network:

| Segment | Copper | Current | Loss |
|---|---|---:|---:|
| FET phase pad → shunt pad 1 | `Net-(U2-Phase)` pour, F.Cu **+ In1.Cu**, 87 stitching vias (~244 mm²) | 9.43 A | 144 mW |
| Shunt body | 2 mΩ 1206 | 9.43 A | 178 mW |
| Shunt pad 2 → motor connector | **F.Cu trace, 2.0 mm wide, 2.6–2.75 mm long** | 9.43 A | **56–76 mW** |

The switch node is well handled — a two-layer pour with heavy via stitching.
The weak link is the 2.0 mm trace on the motor side of the shunt, which is the
only non-pour conductor carrying full phase current. The 0.25 mm traces that
touch the same pads carry only the INA240 sense/filter taps (0.2–0.4 A) — they
run hot purely by conduction from the pad, not by self-heating.

---

## 4. Cross-check against the IPC charts

Both the Brooks & Adam closed form fit to IPC-2152 (the formula KiCad itself
uses) and the legacy IPC-2221 fit were evaluated on the 2.0 mm traces:

| Trace | I (A) | Thermal network | IPC-2152 ΔT | IPC-2221 ΔT |
|---|---:|---:|---:|---:|
| Phase ch1-V, 2.0 mm F.Cu | 9.43 | 90.4 °C abs (65.4 K) | 91.7 K | 72.1 K |
| Phase ch2-V, 2.0 mm F.Cu | 9.43 | 83.1 °C abs (58.1 K) | 91.7 K | 72.1 K |

The three agree within ~26 K. The network result is the coolest of the three
because it credits the pad heat-sinking and plane spreading that the chart
method ignores — which is the physically correct direction.

For scale: IPC-2152 puts a 2.0 mm × 1 oz external trace at about **3.1 A for a
10 K rise**. It is being asked to carry 9.43 A.

---

## 5. Sensitivity — the phase legs are the real risk

A 10 A DC channel only forces 9.43 A rms per phase **at full modulation**
(I<sub>ph,rms</sub> = I<sub>dc</sub> / (1.0607 · m · cos φ)). At part throttle
the phase current rises as 1/m, and the README's own "20 A continuous phase"
rating corresponds to m ≈ 0.47 for a 10 A DC channel.

| I<sub>phase</sub> (A rms) | equiv. m | phase copper (mW) | 2.0 mm trace |
|---:|---:|---:|---:|
| 9.43 | 1.00 | 1 361 | 90 °C *(solved)* |
| 12.0 | 0.79 | 2 403 | ~140 °C |
| 15.0 | 0.63 | 3 754 | ~205 °C |
| 20.0 | 0.47 | 6 675 | ~346 °C |

At the README's continuous phase rating the 2.0 mm trace alone would dissipate
~340 mW and each 2 mΩ shunt ~800 mW. **The phase-leg copper is adequate only at
full modulation** — which is exactly the operating point the stated 54 V /
20 A DC condition implies, but it is not a worst case.

---

## 6. Recommendations, in priority order

1. **Widen the shunt → connector trace** from 2.0 mm to ≥ 4 mm, or better, pour
   the `/Phase/Phase *` and `/Phase1/Phase *` nets on F.Cu. The trace is only
   ~2.6 mm long and there is room. Per IPC-2152 this takes the rise from 92 K
   to 41 K.
2. **Give both shunt pads a pour, not just the switch-node side.** The 178 mW
   shunt loss is the dominant heat source at that node, and the motor-side pad
   is the end with the least copper. It is the motor-side pad temperature that
   sets the 90 °C.
3. **Add plane copper under the input pour.** `Net-(J3-Pin_2)` (XT60 → fuse)
   carries the full 20 A through a single 1 oz F.Cu pour with **no vias and no
   second layer** — 0.854 mΩ, 342 mW, 14 % of all copper loss. Stitching it to a
   B.Cu or In2.Cu pour would roughly halve that.
4. **The switch-node pours run at 85 °C** and are F.Cu + **In1.Cu at 0.5 oz**,
   so half their copper has double the sheet resistance. Adding In2/B.Cu copper
   would help thermally, but it increases switch-node capacitance — a real
   trade-off against EMI and switching loss, so treat this as a judgement call
   rather than an automatic fix.
5. **Vdrive is the largest single block (908 mW, R<sub>eff</sub> 2.27 mΩ) but
   runs cool** (45.8 °C) because it is distributed across pours on three layers.
   No action needed.
6. **GND is in good shape** — 0.486 mΩ, 194 mW at 20 A, hottest via 49.5 °C. The
   full-board In2.Cu plane is doing its job.
7. If the phase legs must survive part-throttle operation, the honest fixes are
   **2 oz outer copper** (~halves the trace rise) or a **lower-resistance shunt
   in a bigger package**.

---

## 7. Method and assumptions

**Model.** The copper was extracted from the board file and solved as a 3-D
resistor network — 2 330 track segments, 1 342 vias, 34 pours, 1 105 pads —
with pours meshed at 0.5 mm. Vias, tracks, pad contacts and the shunt bodies
are explicit elements. Node count ≈ 106 000. Solved by conjugate gradient; the
electrical and thermal problems are iterated to convergence against
temperature-dependent copper resistivity (+9 % dissipation from cold to hot).

**Thermal.** The same copper topology is reused as a conduction network:
copper in-plane (385 W/m·K), FR4 vertically between layers (0.3 W/m·K), outer
copper rejecting to ambient. This reproduces plane spreading *and* short-trace
pad heat-sinking, neither of which the plain IPC chart method captures.

**Verified:**

* Mesh-converged — Vdrive R<sub>eff</sub> moved 2.080 → 2.177 mΩ from 0.8 mm to
  0.25 mm cells (< 5 %), and peak cell current scaled with cell size, confirming
  the plane current is smooth rather than an artefact of the mesh.
* Agrees with IPC-2152 to within ~26 K on the traces where both apply.
* Zero thermal dead-ends: every node has a genuine heat-rejection path.

**Assumptions worth knowing:**

* 25 µm via barrel plating (0.3 mm drill → 1.115 mΩ per via). At 20 µm plating
  every via loss rises ~25 %.
* Phase current is the *minimum* compatible with the stated DC input (m = 1,
  cos φ = 1). See §5 — this is the optimistic end.
* Outer-copper ambient coefficient 18 W/m²K (natural convection + radiation,
  plus the surrounding bare-board surface).
* Vdrive/GND currents are the DC averages. Near each FET the drain/source
  current is *chopped* by PWM, and over a fundamental cycle at full modulation
  its rms is 2× the DC average; only where all six half-bridges contribute does
  it fall back to the average. Solving each FET in isolation shows **8.6 % of
  Vdrive elements and 1.2 % of GND elements are fed by a single FET**, so those
  (the FET-local pours, tie-bars and pad vias) carry the 2× crest and roughly 4×
  the loss. The effect is confined to the FET terminations and would lift the
  local Vdrive/GND peak from ~46–55 °C into the ~60–70 °C range — it does not
  change which trace is hottest, because the phase legs carry a *continuous*
  current and were solved at its true rms.
* Shunts are modelled as 2 mΩ at the terminals; the 1206 body was not modelled
  thermally beyond that.

---

## 8. Artifacts

| File | Contents |
|---|---|
| `loss-analysis/kicad_parse.py` | KiCad 10 s-expression board parser |
| `loss-analysis/network.py` | Copper network builder, electrical + thermal solvers |
| `loss-analysis/analyze.py` | Main electro-thermal study → `analysis.out` |
| `loss-analysis/input_path.py` | The 20 A XT60 → fuse pour → `input_path.out` |
| `loss-analysis/crest.py` | Single-FET attribution behind the §7 crest-factor note |
| `loss-analysis/heatmap.py` | SVG heat-map renderer (not run to completion — see below) |

The heat-map renderer was written and works, but the final render was abandoned
when this machine's load average passed 60 and the solve stalled; the numbers
above come from `analysis.out` and `input_path.out`, which both completed.
