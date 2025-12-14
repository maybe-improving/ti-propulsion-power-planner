# Terra Invicta Propulsion and Power Planner

A Streamlit-based analysis tool for **Terra Invicta** that helps you reason about:

- Which **drives** and **power plants** are obsolete (dominated)  
- Which **drive + reactor combinations** are valid and efficient  
- How those combos behave for a given **reference ship**  
- Whether specific **mission targets** (Δv + acceleration) are feasible

> Not affiliated with Hooded Horse, Pavonis Interactive, or the Terra Invicta team.  
> This is a fan-made analysis tool.

---

## Live app

https://ti-propulsion-power-planner.streamlit.app

---

## Features

- **Local-only data loading**  
  Uses Terra Invicta **JSON template files** (from the game install) with no network access:
  - `TIDriveTemplate.json` – drives
  - `TIPowerPlantTemplate.json` – power plants (reactors)
  - `TIProjectTemplate.json` – research projects (used for unlock cost + tech suggestions)
  The app searches for templates in this order:
  1) `TI_TEMPLATES_DIR` environment variable (recommended)
  2) Default Steam install path (Windows)
  3) Current working directory (next to the script)

- **Drive obsolescence analysis**
  - Unlock drives by **family** (e.g. “Tungsten Resistojet” → all x1..x6 variants).
  - Marks drive variants as **Obsolete** if they’re dominated on:
    - Thrust  
    - Exhaust velocity  
    - Power-use efficiency  
    - Drive mass  
    - Fuel scarcity (scarce fuel is never allowed to dominate non‑scarce)  
    - Optional: backup power behavior (Always / When Not Thrusting / When Thrusting / Never)
  - Option to **prevent intra-family dominance**  
    (“Don’t mark drives obsolete within the same family/class”).

- **Reactor (power plant) obsolescence**
  - Marks reactors as obsolete based on:
    - Max output (GW)  
    - Specific power (tons/GW)  
    - Efficiency  
    - General-use flag  
    - Optional: crew size (lower crew is better when enabled)
  - Option to **care / don’t care about crew size** in dominance.

- **Resource-aware fuel economics**
  - You declare resources as **abundant or scarce**:
    - Water, Volatiles, Base metals, Noble metals, Fissiles, Antimatter, Exotics
  - Drives that use scarce resources in their per‑tank propellant mix are flagged as **Uses Scarce Propellant**.
  - A configurable **Expensive Fuel Score**:
    - Weighted sum of per‑tank resource usage (weights controlled by sliders).
    - Appears in drive tables and combination tables.
    - Influences combo-level dominance.

- **Reference ship modeling**
  - Global sliders (with numeric input boxes) for:
    - Reference payload mass (tons) – up to 300,000 t  
    - Reference propellant mass (tons) – up to 300,000 t
  - For each valid drive + reactor combo, the app computes:
    - Ref Delta-v (km/s)  
    - Ref Cruise Accel (g)  
    - Ref Combat Accel (g)  
    - Total Wet Mass (tons)  
    - Power Ratio (PP/Drive)  
    - Reactor Enough Power? (reactor output vs drive power usage)
  - Note: the drive power requirement is modeled as **required input power**, which accounts for drive efficiency.

- **Valid drive + power plant combinations**
  - Considers only:
    - Non-obsolete drives  
    - Non-obsolete reactors  
    - Combos where the reactor can supply enough power for the drive
  - Respects the game’s **Required Power Plant** / reactor class rules.
  - Includes combo-level dominance:
    - A combo is dominated if another has:
      - ≥ Delta-v, ≥ accel, ≥ power ratio, and ≤ Expensive Fuel Score  
    - Optional **Hide dominated combos** toggle.

- **Scatterplot**
  - Plots any two of:
    - Drive Expensive Fuel Score  
    - Ref Delta-v (km/s)  
    - Ref Cruise Accel (g)  
    - Ref Combat Accel (g)  
    - Power Ratio (PP/Drive)  
    - Total Wet Mass (tons)
  - Default axes: **Ref Cruise Accel (g)** vs **Ref Delta-v (km/s)**.
  - If you pick the same metric on both axes, the app shows a message instead of a broken plot.

- **Mission feasibility search**
  - You specify:
    - Target Δv (km/s)  
    - Target acceleration (g), and whether to interpret it as **cruise** or **combat** accel  
    - Minimum payload mass (tons)
  - For each valid combo, the app searches over payload and propellant mass to find:
    - A feasible configuration that meets those targets (if one exists).
  - Outputs:
    - Drive, Power Plant  
    - Payload mass, Propellant mass  
    - Result Delta-v (km/s)  
    - Result Accel (g)  
    - Max Feasible Payload (tons) (analytic upper bound for that mission target)

- **Profile download/upload (JSON)**
  - **Download profile JSON**: saves your current configuration:
    - Unlocked drive families & reactors  
    - Resource abundance flags  
    - Optional obsolescence preferences  
    - Reference masses  
    - Fuel cost weights
    - Tech path suggestion settings (max steps, top-N, hide-zero)
  - **Upload profile JSON**: restores those settings.
  - Upload is validated:
    - Size-bounded to a small, computed max profile size  
    - JSON schema & ranges are sanitized before applying  
    - No arbitrary code execution or server-side disk writes

- **Built for deployment**
  - No filesystem writes (apart from user-side downloads).  
  - No external network calls.  
  - Plays nicely with Streamlit Community Cloud.

---

## Installation (local)

### 1. Clone the repository

  git clone https://github.com/maybe-improving/ti-propulsion-power-planner.git
    cd ti-propulsion-power-planner

### 2. Point the app at Terra Invicta Templates

The app needs these game JSON templates:

- `TIDriveTemplate.json`
- `TIPowerPlantTemplate.json`
- `TIProjectTemplate.json`

Recommended: set an environment variable to your Terra Invicta `Templates` folder:

**Windows (PowerShell):**

    $env:TI_TEMPLATES_DIR = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Terra Invicta\\TerraInvicta_Data\\StreamingAssets\\Templates"

Alternatively, copy the JSON files into the repo root (next to `ti_propulsion_power_planner.py`).

### 3. Install dependencies

It’s recommended to use a virtual environment:

    python -m venv .venv
    source .venv/bin/activate        # On Windows: .venv\Scripts\activate
    pip install --upgrade pip
    pip install -r requirements.txt

The `requirements.txt` should include at least:

    streamlit
    pandas
    altair

(with reasonable version ranges).

### 4. Run the app

    streamlit run ti_propulsion_power_planner.py

Then open the URL printed by Streamlit (typically `http://localhost:8501`).

---

## Usage overview

### 1. Global Settings (sidebar)

- **Resource abundance**  
  Mark which resources are abundant. Drives using non-abundant resources in their tank mix are marked as using **scarce propellant**, which affects dominance.

- **Optional obsolescence parameters**
  - Care about drives that provide backup power when idle  
  - Care about crew size (for reactors)

- **Drive dominance options**
  - Don’t mark drives obsolete within the same family/class  
  - Hide dominated combos (combo-level obsolete)

- **Fuel cost weights**  
  Sliders + numeric inputs for each resource weight (Water, Volatiles, Base metals, Noble metals, Fissiles, Antimatter, Exotics).

- **Reference ship**  
  Sliders + numeric inputs for:
  - Reference payload mass (tons)  
  - Reference propellant mass (tons)

### 2. Unlocked Content

At the top of the main page:

- **Drives (families)**  
  Unlock drive families, which automatically include their x1..x6 variants.

- **Power Plants**  
  Unlock specific reactors by name.

You can:

- Search  
- Add one  
- Unlock all  
- Clear all  
- Remove selected items

### 3. Drives / Power Plants tabs

Two tabs in the middle:

- **🚀 Drives**: Drive Obsolescence table  
- **⚡ Power Plants**: Reactor Obsolescence table  

Each tab has:

- Obsolescence info (Obsolete / Dominated By)  
- Column visibility checkboxes on the left  
- Autosizing tables on the right  

Each tab also includes a **Tech path suggestions** table (under the obsolescence table) that proposes reachable drives/reactors to research next. Suggestions are ranked by dominance impact per research cost.

Key suggestion metrics:

- **New Dominances**: how many *additional* items the suggestion would newly dominate, excluding items already dominated by at least one currently unlocked drive/reactor.
- **New Domination Efficiency**: `(New Dominances × 1000) / Unlock Total Research Cost`.

### 4. Valid Drive + Power Plant combinations

Below the tabs:

- Shows all **non-obsolete** drive + reactor combos where:
  - Class requirements are satisfied  
  - Reactor has enough power for the drive
- Each row includes:
  - Drive & reactor names and classes  
  - Ref Delta-v, Ref Cruise/Combat Accel, Power Ratio  
  - Total Wet Mass  
  - Fuel cost score and other metrics

Power note: in the combos table, **Drive Power (GW)** is based on the drive’s **required input power**, not just ideal exhaust power.
- Combo-level dominance can be hidden via the sidebar toggle.
- Column visibility checkboxes for this table as well.

### 5. Scatterplot

Still below the combination table:

- Choose an X-axis and Y-axis metric.  
- Points are interactive with tooltips:
  - Drive, Power Plant  
  - X metric, Y metric  
- If the same metric is selected on both axes, the app shows an informational message instead of a degenerate plot.

### 6. Mission Feasibility Search

At the bottom:

1. Set:
   - Target Δv (km/s)  
   - Accel constraint type (combat vs cruise)  
   - Target acceleration (g)  
   - Minimum payload mass (tons)
2. Click **Calculate mission feasibility**.
3. The results table shows, for each feasible combo:
   - Drive, Power Plant  
   - Payload Mass, Propellant Mass  
   - Result Delta-v, Result Accel  
   - Max Feasible Payload  

---

The app doesn’t write to server disk and doesn’t call external APIs, so it’s well-suited for Streamlit Cloud.

---
