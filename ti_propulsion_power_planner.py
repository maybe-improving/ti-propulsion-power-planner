"""
Terra Invicta Propulsion and Power Planner
==========================================

Streamlit app – JSON-from-game-data version.

- Reads drive & reactor data directly from Terra Invicta game files:
    - TIDriveTemplate.json
    - TIPowerPlantTemplate.json
- By default it looks for those files in:
    1) The folder pointed to by the TI_TEMPLATES_DIR environment variable, or
    2) The default Steam path on Windows:
       C:\\Program Files (x86)\\Steam\\steamapps\\common\\Terra Invicta\\TerraInvicta_Data\\StreamingAssets\\Templates
    3) The current working directory (next to this script).

- Starts with NO drives or reactors unlocked.
- Unlock drives by FAMILY (e.g. "Tungsten Resistojet" → all x1..x6 variants).
- Obsolescence respects resource scarcity and optional parameters:
    - care about drives that provide backup power when idle
    - care about crew size (for reactors)
- Saves & loads profile via JSON download/upload (deployment-ready).
- Column‑visibility checkboxes:
    - Drive Obsolescence
    - Power Plant Obsolescence
    - Valid Drive + Power Plant combinations
- Dataframe widgets remount (autosize columns) when table structure changes.
- Valid combinations table only uses NON‑obsolete drives/reactors and checks:
    - Drive's "Required Power Plant" vs reactor "Class"
    - Derived metrics: delta‑v, acceleration, expensive fuel score, power ratio, etc.
- Sidebar sliders + number inputs for:
    - Reference payload / propellant mass
    - Fuel cost weights (water, volatiles, base metals, noble metals,
      fissiles, antimatter, exotics)
- Combined table + scatterplot sit BELOW the Drives/Power Plants tabs
  and automatically filter out combos with insufficient reactor power.
- Optional:
    - "Don’t mark drives obsolete within the same family/class" toggle
    - "Hide dominated combos" checkbox (combo‑level dominance).
- Reactor mass in combos is SCALED to the drive's power requirement.
- Mission feasibility search:
    - User inputs target Δv, accel constraint (cruise/combat), and MINIMUM payload mass
    - Tool searches over payload & propellant mass for each combo
    - Outputs a table with:
        - Payload Mass (tons)
        - Propellant Mass (tons)
        - Result Delta-v (km/s)
        - Result Accel (g or milli-g, based on display option)
        - Max Feasible Payload (tons)

New in this version:
- Loads drives & reactors from the Terra Invicta game JSON files
  (TIDriveTemplate.json, TIPowerPlantTemplate.json) instead of wiki HTML.
- Option in Global Settings to display accelerations in milligees instead of g.
- One-time JS tweak to set a wide default sidebar width but keep it user‑adjustable.
- Profile upload protection: do not re-apply the same uploaded profile every rerun.
- New columns:
    - Drives: "Dominates (count)" – how many other drives each drive dominates.
    - Power plants: "Dominates (count)" – how many other reactors each reactor dominates.
"""

import os
import re
import textwrap
import json
import hashlib
import math
from typing import Dict, Any, List, Optional

import pandas as pd
import streamlit as st
import altair as alt


# ---------------------------------------------------------------------------
# Game data location
# ---------------------------------------------------------------------------

# Default Steam install path on Windows. If you use a different platform or
# custom location, either:
#   - Set the TI_TEMPLATES_DIR environment variable to the folder that actually
#     contains TIDriveTemplate.json and TIPowerPlantTemplate.json, OR
#   - Edit DEFAULT_GAME_DIR below.
DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Terra Invicta"

DRIVE_JSON_FILENAME = "TIDriveTemplate.json"
PP_JSON_FILENAME = "TIPowerPlantTemplate.json"
PROJECT_JSON_FILENAME = "TIProjectTemplate.json"



def _find_template_file(filename: str) -> str:
    """
    Try to locate a given Terra Invicta templates JSON file.

    Search order:
      1) TI_TEMPLATES_DIR environment variable (if set)
      2) Default Steam path on Windows
      3) Current working directory (file next to the script)

    Returns:
        Full filesystem path if found, or raises RuntimeError otherwise.
    """
    candidates: List[str] = []

    env_dir = os.environ.get("TI_TEMPLATES_DIR", "").strip()
    if env_dir:
        candidates.append(os.path.join(env_dir, filename))

    default_templates_dir = os.path.join(
        DEFAULT_GAME_DIR,
        "TerraInvicta_Data",
        "StreamingAssets",
        "Templates",
    )
    candidates.append(os.path.join(default_templates_dir, filename))

    # Fallback: same folder as this script / current working dir
    candidates.append(os.path.join(os.getcwd(), filename))

    for path in candidates:
        if os.path.exists(path):
            return path

    raise RuntimeError(
        f"Could not find {filename!r}.\n\n"
        "The app looks in:\n"
        "  1) TI_TEMPLATES_DIR environment variable (if set)\n"
        "  2) Default Steam path on Windows\n"
        "  3) Current working directory\n\n"
        "Set TI_TEMPLATES_DIR to your 'Templates' folder, or copy the JSON "
        "next to this script."
    )


# ---------------------------------------------------------------------------
# Help file HTML (downloadable)
# ---------------------------------------------------------------------------

HELP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Terra Invicta Propulsion and Power Planner - Help</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
      margin: 1.5rem;
      max-width: 900px;
    }
    h1, h2, h3 {
      color: #222;
    }
    code {
      font-family: "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      background: #f3f3f3;
      padding: 0.1em 0.3em;
      border-radius: 3px;
    }
    pre {
      background: #f3f3f3;
      padding: 0.75rem 1rem;
      border-radius: 4px;
      overflow-x: auto;
    }
    ul, ol {
      margin-left: 1.25rem;
    }
    .tag {
      display: inline-block;
      padding: 0.1rem 0.4rem;
      border-radius: 4px;
      background: #eee;
      font-size: 0.85em;
    }
  </style>
</head>
<body>
  <header>
    <h1>Terra Invicta Propulsion and Power Planner</h1>
    <p>
      This tool helps you reason about ship drives and power plants in
      <strong>Terra Invicta</strong>:
      which drives/reactors are dominated, which combinations are valid,
      and how they behave for a reference ship and target missions.
    </p>
  </header>

  <main>
    <h2>1. Data &amp; requirements</h2>
    <p>
      The app reads two local JSON files from your Terra Invicta installation:
    </p>
    <ul>
      <li><code>TIDriveTemplate.json</code> – drive data</li>
      <li><code>TIPowerPlantTemplate.json</code> – power plant (reactor) data</li>
    </ul>
    <p>
      It looks for these files in the following locations:
    </p>
    <ol>
      <li>The folder specified by the <code>TI_TEMPLATES_DIR</code> environment variable (if set)</li>
      <li>
        The default Steam path on Windows:<br />
        <code>C:\Program Files (x86)\Steam\steamapps\common\Terra Invicta\TerraInvicta_Data\StreamingAssets\Templates</code>
      </li>
      <li>
        The current working directory (next to the app script), if you copy the
        JSON files there manually
      </li>
    </ol>
    <p>
      If the app cannot find the JSON files, it will show a clear error message
      with hints on how to fix the path.
    </p>

    <h2>2. Sidebar: help &amp; profiles</h2>
    <h3>2.1 Help</h3>
    <p>
      At the top of the sidebar you can click
      <strong>“Download help file”</strong> to get this HTML help on disk.
    </p>

    <h3>2.2 Profiles</h3>
    <p>
      Profiles store:
    </p>
    <ul>
      <li>Unlocked drive families</li>
      <li>Unlocked reactors</li>
      <li>Resource abundance flags</li>
      <li>Optional obsolescence parameters</li>
      <li>Reference payload/propellant masses</li>
      <li>Fuel cost weights</li>
      <li>Acceleration display units setting</li>
    </ul>
    <p>
      Use the buttons under <strong>Profile</strong>:
    </p>
    <ul>
      <li><span class="tag">Download profile JSON</span> – saves current settings as a JSON file</li>
      <li>
        <span class="tag">Upload profile JSON</span> – select a previously saved JSON file
        to restore settings
      </li>
    </ul>
    <p>
      This works both locally and on Streamlit Cloud without any server-side disk storage.
    </p>

    <h2>3. Global settings</h2>
    <h3>3.1 Resource abundance</h3>
    <p>
      These checkboxes describe which resources are “plentiful” in your campaign:
    </p>
    <ul>
      <li>Water abundant</li>
      <li>Volatiles abundant</li>
      <li>Base metals abundant</li>
      <li>Noble metals abundant</li>
      <li>Fissiles abundant</li>
      <li>Antimatter abundant</li>
      <li>Exotics abundant</li>
    </ul>
    <p>
      Drives whose per-tank propellant requires any resource marked as
      <em>not abundant</em> are flagged as using
      <strong>scarce propellant</strong>, and that affects drive dominance:
      a drive that uses scarce fuel cannot dominate a drive that does not.
    </p>

    <h3>3.2 Optional obsolescence parameters</h3>
    <ul>
      <li>
        <strong>Care about drives that provide backup power when idle</strong><br />
        When enabled, drives that provide power when idle (backup mode
        <em>Always</em> or <em>DriveIdle</em>) are favoured:
        <ul>
          <li>A drive without idle backup cannot dominate one that has it.</li>
          <li>Idle backup can break ties and make a drive strictly better.</li>
        </ul>
      </li>
      <li>
        <strong>Care about crew size</strong><br />
        When enabled, the reactor dominance logic considers crew as a dimension:
        <ul>
          <li>Lower crew is strictly better.</li>
          <li>A reactor with higher crew cannot dominate one with lower crew.</li>
        </ul>
        When disabled, crew size is ignored for reactor obsolescence.
      </li>
    </ul>

    <h3>3.3 Drive dominance options</h3>
    <ul>
      <li>
        <strong>Don’t mark drives obsolete within the same family/class</strong><br />
        Prevents intra-family dominance (e.g. Resistojet x2 never marks Resistojet x1 obsolete),
        so you can always see the full progression within a drive family.
      </li>
      <li>
        <strong>Hide dominated combos (combo-level obsolete)</strong><br />
        Applies to the combined Drive + Power Plant table:
        only non-dominated combinations are shown when this is checked.
      </li>
    </ul>

    <h3>3.4 Fuel cost weights</h3>
    <p>
      These sliders set a scalar “Expensive Fuel Score” for each drive, based on its
      per-tank propellant mix:
    </p>
    <ul>
      <li>Water weight</li>
      <li>Volatiles weight</li>
      <li>Base metals weight</li>
      <li>Noble metals weight</li>
      <li>Fissiles weight</li>
      <li>Antimatter weight</li>
      <li>Exotics weight</li>
    </ul>
    <p>
      Drives that lean on high-weight resources get a larger Expensive Fuel Score.
      This appears in the Drives table and the combos table, and is used in
      combo-level dominance.
    </p>

    <h3>3.5 Reference ship (for Δv / accel)</h3>
    <p>
      These control the reference ship mass used in the Drive+Reactor combos:
    </p>
    <ul>
      <li><strong>Reference payload mass (tons)</strong> – up to 300,000 tons</li>
      <li><strong>Reference propellant mass (tons)</strong> – up to 300,000 tons</li>
    </ul>
    <p>
      For each valid combo, the app computes:
    </p>
    <ul>
      <li>Ref Delta-v (km/s)</li>
      <li>Ref Cruise Accel (g or milli-g)</li>
      <li>Ref Combat Accel (g or milli-g)</li>
      <li>Total Wet Mass (tons)</li>
    </ul>
    <p>
      Changing these sliders immediately updates the combos table,
      scatterplot, and mission feasibility results.
    </p>

    <h3>3.6 Display options</h3>
    <ul>
      <li>
        <strong>Display accelerations in milligees</strong><br />
        When enabled, all displayed acceleration values in the tables, scatterplot,
        and mission results are shown in milli-g instead of g.
        Internally, calculations are still performed in g; this only changes display units.
      </li>
    </ul>

    <h2>4. Unlocked content</h2>
    <h3>4.1 Drives (families)</h3>
    <p>
      Drives are unlocked by <strong>family</strong>, e.g. “Tungsten Resistojet”.
      Adding a family automatically unlocks all its x1..x6 variants.
    </p>
    <ul>
      <li>Use the search box to filter drive families.</li>
      <li>“Add Drive Family” – add the selected family to your unlocked list.</li>
      <li>“Unlock ALL drive families” – unlocks everything.</li>
      <li>“Clear all drives” – removes all unlocked families.</li>
      <li>“Remove selected drive families” – remove specific families.</li>
    </ul>

    <h3>4.2 Power plants (reactors)</h3>
    <p>
      Reactors are unlocked one by one by name (not by family).
    </p>
    <ul>
      <li>Use the search box to filter reactors.</li>
      <li>“Add Reactor” – add the selected reactor to your unlocked list.</li>
      <li>“Unlock ALL reactors” – unlocks everything.</li>
      <li>“Clear all reactors” – removes all unlocked reactors.</li>
      <li>“Remove selected reactors” – remove specific ones.</li>
    </ul>

    <h2>5. Drive &amp; reactor obsolescence tables</h2>
    <h3>5.1 Drives</h3>
    <p>
      The Drives tab shows each unlocked drive variant (x1..x6) and whether it is
      marked <strong>Obsolete</strong> (dominated) based on:
    </p>
    <ul>
      <li>Thrust (higher is better)</li>
      <li>Exhaust Velocity (higher is better)</li>
      <li>Power Use Efficiency (higher is better)</li>
      <li>Drive Mass (lower is better)</li>
      <li>Fuel scarcity (non-scarce is better)</li>
      <li>Idle backup power (if that option is enabled)</li>
    </ul>
    <p>
      Each drive also has a <strong>“Dominates (count)”</strong> column, indicating
      how many other drive variants it strictly dominates under the current settings.
      You can toggle which columns are visible using the checkboxes on the left.
    </p>

    <h3>5.2 Power plants</h3>
    <p>
      The Power Plants tab shows each unlocked reactor and whether it is dominated
      based on:
    </p>
    <ul>
      <li>Max Output (GW) – higher is better</li>
      <li>Efficiency – higher is better</li>
      <li>General Use flag – True is better</li>
      <li>Specific Power (tons/GW) – lower is better</li>
      <li>Crew – lower is better if “care about crew size” is enabled</li>
    </ul>
    <p>
      Each reactor also has a <strong>“Dominates (count)”</strong> column, indicating
      how many other reactors it strictly dominates.
    </p>

    <h2>6. Valid Drive + Power Plant combinations</h2>
    <p>
      Below the tabs, the app lists all valid, non-obsolete (drive, reactor) combos
      where the reactor has enough power for the drive. For each combo it computes:
    </p>
    <ul>
      <li>Ref Delta-v (km/s)</li>
      <li>Ref Cruise Accel (g or milli-g)</li>
      <li>Ref Combat Accel (g or milli-g)</li>
      <li>Power Ratio (PP/Drive)</li>
      <li>Total Wet Mass (tons)</li>
      <li>Drive Expensive Fuel Score</li>
    </ul>
    <p>
      A combo-level dominance check can mark combinations as obsolete; when
      “Hide dominated combos” is checked, dominated combos are removed from this table.
    </p>

    <h2>7. Scatterplot</h2>
    <p>
      You can visualize the non-dominated combos in a 2D scatterplot using:
    </p>
    <ul>
      <li>Drive Expensive Fuel Score</li>
      <li>Ref Delta-v (km/s)</li>
      <li>Ref Cruise Accel (g or milli-g)</li>
      <li>Ref Combat Accel (g or milli-g)</li>
      <li>Power Ratio (PP/Drive)</li>
      <li>Total Wet Mass (tons)</li>
    </ul>
    <p>
      By default, the plot shows <strong>Ref Cruise Accel</strong> on the X-axis
      and <strong>Ref Delta-v (km/s)</strong> on the Y-axis.
      If you choose the same metric for both axes, the app shows a friendly message
      instead of a degenerate chart.
    </p>

    <h2>8. Mission feasibility search</h2>
    <p>
      At the bottom of the page, the Mission Feasibility Search lets you specify:
    </p>
    <ul>
      <li>Target Δv (km/s)</li>
      <li>Acceleration constraint:
        <ul>
          <li>Combat acceleration (g)</li>
          <li>Cruise acceleration (g)</li>
        </ul>
      </li>
      <li>Minimum payload mass (tons, up to 300,000)</li>
    </ul>
    <p>
      For each valid combo, the app searches over a grid of payload and propellant
      masses to find a feasible configuration that meets both Δv and accel targets.
      Results include:
    </p>
    <ul>
      <li>Payload Mass (tons)</li>
      <li>Propellant Mass (tons)</li>
      <li>Result Delta-v (km/s)</li>
      <li>Result Accel (g or milli-g, based on the display setting)</li>
      <li>Max Feasible Payload (tons)</li>
    </ul>
  </main>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

DEFAULT_REF_PAYLOAD_TONS = 1000.0
DEFAULT_REF_PROPELLANT_TONS = 1000.0

DEFAULT_FUEL_WEIGHTS = {
    "water": 1.0,
    "volatiles": 1.0,
    "metals": 1.0,
    "nobleMetals": 1.0,
    "fissiles": 5.0,
    "antimatter": 20.0,
    "exotics": 20.0,
}

PROP_TRANSLATION = {
    "ReactionProducts": "Reaction Products",
    "Anything": "Anything",
    "Hydrogen": "Hydrogen",
    "Water": "Water",
    "NobleGases": "Noble Gases",
    "Volatiles": "Volatiles",
    "Metals": "Metals",
}

DRIVE_PROP_RESOURCE_COLS = {
    "water": "perTankPropellantMaterials/water",
    "volatiles": "perTankPropellantMaterials/volatiles",
    "metals": "perTankPropellantMaterials/metals",
    "nobleMetals": "perTankPropellantMaterials/nobleMetals",
    "fissiles": "perTankPropellantMaterials/fissiles",
    "antimatter": "perTankPropellantMaterials/antimatter",
    "exotics": "perTankPropellantMaterials/exotics",
}

PP_BUILD_RESOURCE_COLS = {
    "water": "weightedBuildMaterials/water",
    "volatiles": "weightedBuildMaterials/volatiles",
    "metals": "weightedBuildMaterials/metals",
    "nobleMetals": "weightedBuildMaterials/nobleMetals",
    "fissiles": "weightedBuildMaterials/fissiles",
    "exotics": "weightedBuildMaterials/exotics",
    "antimatter": "weightedBuildMaterials/antimatter",
}

BACKUP_MODE_RAW_VALUES = {"Always", "DriveIdle", "DriveActive", "Never"}


# ---------------------------------------------------------------------------
# Data loading & cleanup
# ---------------------------------------------------------------------------

def _compute_drive_family_name(display_name: str) -> str:
    if not isinstance(display_name, str):
        return str(display_name)
    return re.sub(r"\s+x[0-9]+$", "", display_name, flags=re.IGNORECASE).strip()


@st.cache_data(show_spinner=True)

def load_drive_data() -> pd.DataFrame:
    """
    Load TIDriveTemplate.json from the Terra Invicta game files (or local folder)
    and convert to a DataFrame with the columns expected by the rest of the app.
    """
    path = _find_template_file(DRIVE_JSON_FILENAME)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # Normalize some key string columns
    for col in ("friendlyName", "dataName", "propellant", "requiredProjectName"):
        if col in df.columns:
            df[col] = df[col].astype(str).fillna("").str.strip()

    df["DisplayName"] = (
        df.get("friendlyName", "")
          .replace({"": None})
          .fillna(df.get("dataName", ""))
          .astype(str)
          .str.strip()
    )

    df["FamilyName"] = df["DisplayName"].apply(_compute_drive_family_name)

    if "disable" in df.columns:
        df = df[df["disable"].astype(str).str.lower() != "true"]

    # Flatten perTankPropellantMaterials (dict) into columns expected in DRIVE_PROP_RESOURCE_COLS
    if "perTankPropellantMaterials" in df.columns:
        materials_series = df["perTankPropellantMaterials"].apply(
            lambda v: v if isinstance(v, dict) else {}
        )
        materials_df = pd.DataFrame(list(materials_series))
        materials_df = materials_df.fillna(0.0)

        for res_key, col_name in DRIVE_PROP_RESOURCE_COLS.items():
            if res_key in materials_df.columns:
                df[col_name] = pd.to_numeric(
                    materials_df[res_key], errors="coerce"
                ).fillna(0.0)
            else:
                df[col_name] = 0.0

    numeric_cols = [
        "thrust_N",
        "EV_kps",
        "efficiency",
        "specificPower_kgMW",
        "flatMass_tons",
        "thrustCap",
    ] + list(DRIVE_PROP_RESOURCE_COLS.values())

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Ensure requiredProjectName exists even if not in source JSON
    if "requiredProjectName" not in df.columns:
        df["requiredProjectName"] = ""

    return df


@st.cache_data(show_spinner=True)

def load_powerplant_data() -> pd.DataFrame:
    """
    Load TIPowerPlantTemplate.json from the Terra Invicta game files (or local folder)
    and convert to a DataFrame with the columns expected by the rest of the app.
    """
    path = _find_template_file(PP_JSON_FILENAME)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    for col in ("friendlyName", "dataName", "powerPlantClass", "generalUse", "requiredProjectName"):
        if col in df.columns:
            df[col] = df[col].astype(str).fillna("").str.strip()

    df["DisplayName"] = (
        df.get("friendlyName", "")
          .replace({"": None})
          .fillna(df.get("dataName", ""))
          .astype(str)
          .str.strip()
    )

    numeric_cols = [
        "maxOutput_GW",
        "specificPower_tGW",
        "efficiency",
        "crew",
    ] + list(PP_BUILD_RESOURCE_COLS.values())

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "generalUse" in df.columns:
        df["generalUse_bool"] = df["generalUse"].astype(str).str.lower().isin(
            ["true", "1", "yes"]
        )
    else:
        df["generalUse_bool"] = True

    if "requiredProjectName" not in df.columns:
        df["requiredProjectName"] = ""

    return df



@st.cache_data(show_spinner=True)
def load_project_data() -> pd.DataFrame:
    """
    Load TIProjectTemplate.json from the Terra Invicta game files (or local folder)
    and return a DataFrame with at least dataName and researchCost.
    """
    path = _find_template_file(PROJECT_JSON_FILENAME)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # Normalize name fields
    for col in ("friendlyName", "dataName"):
        if col in df.columns:
            df[col] = df[col].astype(str).fillna("").str.strip()

    # Ensure researchCost exists as numeric
    if "researchCost" in df.columns:
        df["researchCost"] = pd.to_numeric(df["researchCost"], errors="coerce").fillna(0.0)
    else:
        df["researchCost"] = 0.0

    return df


def build_project_graph(project_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Build a dependency graph of projects from TIProjectTemplate.

    Each node is keyed by dataName and has:
      - cost: researchCost
      - prereqs: list of prerequisite project dataNames

    The main prerequisite field is 'prereqs' (a list).
    In addition, any fields starting with 'altPrereq' that contain
    a non-empty string are treated as alternative prerequisites.
    """
    graph: Dict[str, Dict[str, Any]] = {}

    for _, row in project_df.iterrows():
        pid = str(row.get("dataName", "")).strip()
        if not pid:
            continue

        cost = float(row.get("researchCost", 0.0))

        prereqs: List[str] = []

        raw_prereqs = row.get("prereqs")
        if isinstance(raw_prereqs, list):
            for v in raw_prereqs:
                if v is None:
                    continue
                s = str(v).strip()
                if s:
                    prereqs.append(s)
        elif isinstance(raw_prereqs, str):
            s = raw_prereqs.strip()
            if s:
                prereqs.append(s)

        for col in row.index:
            if not isinstance(col, str):
                continue
            if not col.startswith("altPrereq"):
                continue
            val = row.get(col)
            if isinstance(val, str):
                s = val.strip()
                if s:
                    prereqs.append(s)

        prereqs = list({p for p in prereqs if p})

        graph[pid] = {
            "cost": cost,
            "prereqs": prereqs,
        }

    return graph


def compute_total_project_costs(project_graph: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """
    Given a project dependency graph, compute total research cost for each project
    including all prerequisite projects recursively (no double-counting).
    """
    memo: Dict[str, float] = {}

    def dfs(pid: str, visiting: set) -> float:
        if pid in memo:
            return memo[pid]
        if pid not in project_graph:
            memo[pid] = 0.0
            return 0.0
        if pid in visiting:
            # Cycle detected; avoid infinite recursion
            return 0.0

        node = project_graph[pid]
        total = float(node.get("cost", 0.0))
        new_visiting = set(visiting)
        new_visiting.add(pid)

        for pre in node.get("prereqs", []):
            total += dfs(pre, new_visiting)

        memo[pid] = total
        return total

    for pid in project_graph.keys():
        dfs(pid, set())

    return memo


def find_backup_power_column(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        series = df[col]
        if not (pd.api.types.is_string_dtype(series) or series.dtype == object):
            continue
        vals = (
            series.dropna()
            .astype(str)
            .str.strip()
            .replace({"": None})
            .dropna()
            .unique()
        )
        if len(vals) == 0:
            continue
        if set(vals).issubset(BACKUP_MODE_RAW_VALUES):
            return col
    return None


def find_drive_required_pp_column(drive_df: pd.DataFrame, pp_df: pd.DataFrame) -> Optional[str]:
    if "powerPlantClass" not in pp_df.columns:
        return None

    plant_classes = (
        pp_df["powerPlantClass"]
        .astype(str)
        .str.strip()
        .replace({"": None})
        .dropna()
        .unique()
        .tolist()
    )
    plant_classes_lower = [c.lower() for c in plant_classes]
    if not plant_classes_lower:
        return None

    candidates: List[tuple] = []

    for col in drive_df.columns:
        series = drive_df[col]
        if not (pd.api.types.is_string_dtype(series) or series.dtype == object):
            continue

        vals = (
            series.dropna()
            .astype(str)
            .str.strip()
            .replace({"": None})
            .dropna()
            .unique()
        )
        if len(vals) == 0:
            continue

        sample = vals[:100]
        total = len(sample)
        matches = 0

        for v in sample:
            v_lower = v.lower()
            v_norm = v_lower.replace("_", " ")

            if v_lower in ("any_general", "any reactor", "any", "any power plant"):
                matches += 1
                continue

            if any(v_lower in cls or v_norm in cls for cls in plant_classes_lower):
                matches += 1

        score = matches / total
        if matches >= 3 and score >= 0.3:
            candidates.append((score, matches, col))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][2]


# ---------------------------------------------------------------------------
# Profile save/load (via JSON download/upload)
# ---------------------------------------------------------------------------

def apply_profile(profile: Dict[str, Any]) -> None:
    st.session_state.unlocked_drive_families = profile.get("unlocked_drive_families", [])
    st.session_state.unlocked_pp = profile.get("unlocked_pp", [])

    ra = profile.get("resource_abundance", {})
    st.session_state["water_abundant"] = bool(ra.get("water", True))
    st.session_state["volatiles_abundant"] = bool(ra.get("volatiles", True))
    st.session_state["metals_abundant"] = bool(ra.get("metals", True))
    st.session_state["nobleMetals_abundant"] = bool(ra.get("nobleMetals", True))
    st.session_state["fissiles_abundant"] = bool(ra.get("fissiles", True))
    st.session_state["antimatter_abundant"] = bool(ra.get("antimatter", True))
    st.session_state["exotics_abundant"] = bool(ra.get("exotics", True))

    st.session_state["care_backup"] = bool(profile.get("care_backup", True))
    st.session_state["care_crew"] = bool(profile.get("care_crew", False))
    st.session_state["ignore_intraclass"] = bool(profile.get("ignore_intraclass", False))
    st.session_state["accel_in_milligees"] = bool(profile.get("accel_in_milligees", False))

    st.session_state["ref_payload_tons"] = float(
        profile.get("ref_payload_tons", DEFAULT_REF_PAYLOAD_TONS)
    )
    st.session_state["ref_propellant_tons"] = float(
        profile.get("ref_propellant_tons", DEFAULT_REF_PROPELLANT_TONS)
    )

    fw = profile.get("fuel_weights", {})
    st.session_state["fuel_weight_water"] = float(fw.get("water", DEFAULT_FUEL_WEIGHTS["water"]))
    st.session_state["fuel_weight_volatiles"] = float(fw.get("volatiles", DEFAULT_FUEL_WEIGHTS["volatiles"]))
    st.session_state["fuel_weight_metals"] = float(fw.get("metals", DEFAULT_FUEL_WEIGHTS["metals"]))
    st.session_state["fuel_weight_nobleMetals"] = float(fw.get("nobleMetals", DEFAULT_FUEL_WEIGHTS["nobleMetals"]))
    st.session_state["fuel_weight_fissiles"] = float(fw.get("fissiles", DEFAULT_FUEL_WEIGHTS["fissiles"]))
    st.session_state["fuel_weight_antimatter"] = float(fw.get("antimatter", DEFAULT_FUEL_WEIGHTS["antimatter"]))
    st.session_state["fuel_weight_exotics"] = float(fw.get("exotics", DEFAULT_FUEL_WEIGHTS["exotics"]))

    # Keep input boxes in sync with sliders
    st.session_state["ref_payload_tons_input"] = st.session_state["ref_payload_tons"]
    st.session_state["ref_propellant_tons_input"] = st.session_state["ref_propellant_tons"]
    st.session_state["fuel_weight_water_input"] = st.session_state["fuel_weight_water"]
    st.session_state["fuel_weight_volatiles_input"] = st.session_state["fuel_weight_volatiles"]
    st.session_state["fuel_weight_metals_input"] = st.session_state["fuel_weight_metals"]
    st.session_state["fuel_weight_nobleMetals_input"] = st.session_state["fuel_weight_nobleMetals"]
    st.session_state["fuel_weight_fissiles_input"] = st.session_state["fuel_weight_fissiles"]
    st.session_state["fuel_weight_antimatter_input"] = st.session_state["fuel_weight_antimatter"]
    st.session_state["fuel_weight_exotics_input"] = st.session_state["fuel_weight_exotics"]


def build_profile_dict() -> Dict[str, Any]:
    return {
        "unlocked_drive_families": st.session_state.get("unlocked_drive_families", []),
        "unlocked_pp": st.session_state.get("unlocked_pp", []),
        "resource_abundance": {
            "water": bool(st.session_state.get("water_abundant", True)),
            "volatiles": bool(st.session_state.get("volatiles_abundant", True)),
            "metals": bool(st.session_state.get("metals_abundant", True)),
            "nobleMetals": bool(st.session_state.get("nobleMetals_abundant", True)),
            "fissiles": bool(st.session_state.get("fissiles_abundant", True)),
            "antimatter": bool(st.session_state.get("antimatter_abundant", True)),
            "exotics": bool(st.session_state.get("exotics_abundant", True)),
        },
        "care_backup": bool(st.session_state.get("care_backup", True)),
        "care_crew": bool(st.session_state.get("care_crew", False)),
        "ref_payload_tons": float(
            st.session_state.get("ref_payload_tons", DEFAULT_REF_PAYLOAD_TONS)
        ),
        "ref_propellant_tons": float(
            st.session_state.get("ref_propellant_tons", DEFAULT_REF_PROPELLANT_TONS)
        ),
        "fuel_weights": {
            "water": float(st.session_state.get("fuel_weight_water", DEFAULT_FUEL_WEIGHTS["water"])),
            "volatiles": float(st.session_state.get("fuel_weight_volatiles", DEFAULT_FUEL_WEIGHTS["volatiles"])),
            "metals": float(st.session_state.get("fuel_weight_metals", DEFAULT_FUEL_WEIGHTS["metals"])),
            "nobleMetals": float(st.session_state.get("fuel_weight_nobleMetals", DEFAULT_FUEL_WEIGHTS["nobleMetals"])),
            "fissiles": float(st.session_state.get("fuel_weight_fissiles", DEFAULT_FUEL_WEIGHTS["fissiles"])),
            "antimatter": float(st.session_state.get("fuel_weight_antimatter", DEFAULT_FUEL_WEIGHTS["antimatter"])),
            "exotics": float(st.session_state.get("fuel_weight_exotics", DEFAULT_FUEL_WEIGHTS["exotics"])),
        },
        "ignore_intraclass": bool(st.session_state.get("ignore_intraclass", False)),
        "accel_in_milligees": bool(st.session_state.get("accel_in_milligees", False)),
    }


def sanitize_profile_dict(
    raw_profile: Any,
    all_drive_families: List[str],
    all_pp_names: List[str],
) -> Dict[str, Any]:
    if not isinstance(raw_profile, dict):
        raise ValueError("Top-level JSON must be an object (dictionary).")

    def to_bool(v, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            t = v.strip().lower()
            if t in ("true", "1", "yes", "y", "on"):
                return True
            if t in ("false", "0", "no", "n", "off"):
                return False
        return default

    def to_float(v, default: float) -> float:
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except Exception:
            return default

    def clamp(x: float, lo: float, hi: float) -> float:
        if x < lo:
            return lo
        if x > hi:
            return hi
        return x

    # unlocked drive families
    udf_raw = raw_profile.get("unlocked_drive_families", [])
    if not isinstance(udf_raw, list):
        udf_raw = []
    drive_set = set(all_drive_families)
    unlocked_drive_families: List[str] = []
    for item in udf_raw:
        if isinstance(item, str) and item in drive_set and item not in unlocked_drive_families:
            unlocked_drive_families.append(item)

    # unlocked power plants
    upp_raw = raw_profile.get("unlocked_pp", [])
    if not isinstance(upp_raw, list):
        upp_raw = []
    pp_set = set(all_pp_names)
    unlocked_pp: List[str] = []
    for item in upp_raw:
        if isinstance(item, str) and item in pp_set and item not in unlocked_pp:
            unlocked_pp.append(item)

    # resource abundance
    ra_raw = raw_profile.get("resource_abundance", {})
    if not isinstance(ra_raw, dict):
        ra_raw = {}
    resource_abundance = {
        "water":       to_bool(ra_raw.get("water", True), True),
        "volatiles":   to_bool(ra_raw.get("volatiles", True), True),
        "metals":      to_bool(ra_raw.get("metals", True), True),
        "nobleMetals": to_bool(ra_raw.get("nobleMetals", True), True),
        "fissiles":    to_bool(ra_raw.get("fissiles", True), True),
        "antimatter":  to_bool(ra_raw.get("antimatter", True), True),
        "exotics":     to_bool(ra_raw.get("exotics", True), True),
    }

    care_backup = to_bool(raw_profile.get("care_backup", True), True)
    care_crew = to_bool(raw_profile.get("care_crew", False), False)
    ignore_intraclass = to_bool(raw_profile.get("ignore_intraclass", False), False)
    accel_in_milligees = to_bool(raw_profile.get("accel_in_milligees", False), False)

    ref_payload_tons = clamp(
        to_float(
            raw_profile.get("ref_payload_tons", DEFAULT_REF_PAYLOAD_TONS),
            DEFAULT_REF_PAYLOAD_TONS,
        ),
        100.0,
        300000.0,
    )
    ref_propellant_tons = clamp(
        to_float(
            raw_profile.get("ref_propellant_tons", DEFAULT_REF_PROPELLANT_TONS),
            DEFAULT_REF_PROPELLANT_TONS,
        ),
        0.0,
        300000.0,
    )

    fw_raw = raw_profile.get("fuel_weights", {})
    if not isinstance(fw_raw, dict):
        fw_raw = {}

    fuel_weights = {
        "water": clamp(
            to_float(fw_raw.get("water", DEFAULT_FUEL_WEIGHTS["water"]),
                     DEFAULT_FUEL_WEIGHTS["water"]),
            0.0, 10.0,
        ),
        "volatiles": clamp(
            to_float(fw_raw.get("volatiles", DEFAULT_FUEL_WEIGHTS["volatiles"]),
                     DEFAULT_FUEL_WEIGHTS["volatiles"]),
            0.0, 10.0,
        ),
        "metals": clamp(
            to_float(fw_raw.get("metals", DEFAULT_FUEL_WEIGHTS["metals"]),
                     DEFAULT_FUEL_WEIGHTS["metals"]),
            0.0, 10.0,
        ),
        "nobleMetals": clamp(
            to_float(fw_raw.get("nobleMetals", DEFAULT_FUEL_WEIGHTS["nobleMetals"]),
                     DEFAULT_FUEL_WEIGHTS["nobleMetals"]),
            0.0, 10.0,
        ),
        "fissiles": clamp(
            to_float(fw_raw.get("fissiles", DEFAULT_FUEL_WEIGHTS["fissiles"]),
                     DEFAULT_FUEL_WEIGHTS["fissiles"]),
            0.0, 20.0,
        ),
        "antimatter": clamp(
            to_float(fw_raw.get("antimatter", DEFAULT_FUEL_WEIGHTS["antimatter"]),
                     DEFAULT_FUEL_WEIGHTS["antimatter"]),
            0.0, 50.0,
        ),
        "exotics": clamp(
            to_float(fw_raw.get("exotics", DEFAULT_FUEL_WEIGHTS["exotics"]),
                     DEFAULT_FUEL_WEIGHTS["exotics"]),
            0.0, 50.0,
        ),
    }

    sanitized = {
        "unlocked_drive_families": unlocked_drive_families,
        "unlocked_pp": unlocked_pp,
        "resource_abundance": resource_abundance,
        "care_backup": care_backup,
        "care_crew": care_crew,
        "ref_payload_tons": ref_payload_tons,
        "ref_propellant_tons": ref_propellant_tons,
        "fuel_weights": fuel_weights,
        "ignore_intraclass": ignore_intraclass,
        "accel_in_milligees": accel_in_milligees,
    }

    return sanitized


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def compute_drive_power_gw(thrust_n: float, ev_kps: float) -> float:
    return thrust_n * ev_kps / 2_000_000.0


def interpret_backup(raw: str) -> str:
    if raw == "Always":
        return "Always"
    if raw == "DriveIdle":
        return "When Not Thrusting"
    if raw == "DriveActive":
        return "When Thrusting"
    return "Never"


def has_idle_backup(raw: str) -> bool:
    return raw in {"Always", "DriveIdle"}


def drive_uses_scarce(row: pd.Series, abundance: Dict[str, bool]) -> bool:
    for res_key in ["water", "volatiles", "metals", "nobleMetals", "fissiles", "antimatter", "exotics"]:
        col = DRIVE_PROP_RESOURCE_COLS.get(res_key)
        if col not in row.index:
            continue
        amount = float(row[col])
        if amount > 0 and not abundance.get(res_key, True):
            return True
    return False



def build_drive_features(
    df: pd.DataFrame,
    abundance: Dict[str, bool],
    backup_col: Optional[str],
    req_pp_col: Optional[str],
    fuel_weights: Dict[str, float],
    project_total_costs: Dict[str, float],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        name = row["DisplayName"]
        family = row.get("FamilyName", "")
        thrust = float(row.get("thrust_N", 0.0))
        ev = float(row.get("EV_kps", 0.0))
        eff = float(row.get("efficiency", 0.0))
        mass = float(row.get("flatMass_tons", 0.0))
        thrust_cap = float(row.get("thrustCap", 0.0))

        power_gw = compute_drive_power_gw(thrust, ev)

        prop_enum = str(row.get("propellant", "")).strip()
        prop_label = PROP_TRANSLATION.get(prop_enum, prop_enum or "Unknown")

        mix_parts: List[str] = []
        exp_score = 0.0
        for res_key, col in DRIVE_PROP_RESOURCE_COLS.items():
            if col not in row.index:
                continue
            val = float(row[col])
            if val > 0:
                display_mass = val * 10.0
                mix_parts.append(f"{display_mass:g} {res_key}")
                if res_key in fuel_weights:
                    exp_score += fuel_weights[res_key] * display_mass
        mix_str = ", ".join(mix_parts) if mix_parts else "—"

        raw_backup = "Never"
        if backup_col and backup_col in row.index:
            raw_backup = str(row[backup_col]).strip()
        backup_mode = interpret_backup(raw_backup)
        idle_backup = has_idle_backup(raw_backup)

        scarce = drive_uses_scarce(row, abundance)

        req_pp_val = ""
        if req_pp_col and req_pp_col in row.index:
            req_pp_val = str(row[req_pp_col]).strip()
        if not req_pp_val:
            req_pp_val = "Any Reactor"

        proj_name = str(row.get("requiredProjectName", "")).strip()
        total_proj_cost = project_total_costs.get(proj_name, 0.0)

        rows.append(
            {
                "Name": name,
                "FamilyName": family,
                "Thrust (N)": thrust,
                "Combat Thrust Multiplier": thrust_cap,
                "Exhaust Velocity (km/s)": ev,
                "Power Use Efficiency": eff,
                "Drive Mass (tons)": mass,
                "Approx. Drive Power (GW)": power_gw,
                "Propellant Type": prop_label,
                "Per-Tank Propellant Mix": mix_str,
                "Backup Power Mode": backup_mode,
                "Has Idle Backup": idle_backup,
                "Uses Scarce Propellant": scarce,
                "Required Power Plant": req_pp_val,
                "Expensive Fuel Score": exp_score,
                "Unlock Project": proj_name,
                "Unlock Total Research Cost": total_proj_cost,
            }
        )

    return pd.DataFrame(rows)



def build_pp_features(df: pd.DataFrame, project_total_costs: Dict[str, float]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        proj_name = str(row.get("requiredProjectName", "")).strip()
        total_proj_cost = project_total_costs.get(proj_name, 0.0)

        rows.append(
            {
                "Name": row["DisplayName"],
                "Class": row.get("powerPlantClass", ""),
                "Max Output (GW)": float(row.get("maxOutput_GW", 0.0)),
                "Specific Power (tons/GW)": float(row.get("specificPower_tGW", 0.0)),
                "Efficiency": float(row.get("efficiency", 0.0)),
                "Crew": float(row.get("crew", 0.0)),
                "General Use": bool(row.get("generalUse_bool", True)),
                "Unlock Project": proj_name,
                "Unlock Total Research Cost": total_proj_cost,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------


def dominates_drive(
    a: pd.Series,
    b: pd.Series,
    care_backup: bool,
    ignore_intraclass: bool,
    class_col: str = "FamilyName",
) -> bool:
    """
    Return True if drive 'a' strictly dominates drive 'b' under the current
    obsolescence rules:
      - Higher or equal thrust, exhaust velocity, and power use efficiency
      - Lower or equal drive mass
      - If care_backup is True, then backup power is treated as a dimension
      - A drive using scarce propellant can *never* dominate one that does not
    """
    # Optionally prevent intra-family/class dominance
    if ignore_intraclass and (class_col in a.index) and (class_col in b.index):
        if a[class_col] == b[class_col]:
            return False

    # Scarce propellant rule: a drive that uses scarce fuel cannot dominate
    # a drive that does not
    if a["Uses Scarce Propellant"] and not b["Uses Scarce Propellant"]:
        return False

    ge_dims = [
        a["Thrust (N)"] >= b["Thrust (N)"],
        a["Exhaust Velocity (km/s)"] >= b["Exhaust Velocity (km/s)"],
        a["Power Use Efficiency"] >= b["Power Use Efficiency"],
    ]
    le_dims = [
        a["Drive Mass (tons)"] <= b["Drive Mass (tons)"],
    ]

    if care_backup:
        # If we care about backup power, a drive that lacks idle backup
        # cannot dominate one that has it.
        if (not a["Has Idle Backup"]) and b["Has Idle Backup"]:
            return False
        ge_dims.append(int(a["Has Idle Backup"]) >= int(b["Has Idle Backup"]))

    if not all(ge_dims) or not all(le_dims):
        return False

    strict_better = (
        (a["Thrust (N)"] > b["Thrust (N)"])
        or (a["Exhaust Velocity (km/s)"] > b["Exhaust Velocity (km/s)"])
        or (a["Power Use Efficiency"] > b["Power Use Efficiency"])
        or (a["Drive Mass (tons)"] < b["Drive Mass (tons)"])
    )

    if care_backup and a["Has Idle Backup"] and not b["Has Idle Backup"]:
        strict_better = True

    # If 'a' uses non-scarce fuel while 'b' uses scarce fuel, that is also
    # treated as a strict improvement.
    if (not a["Uses Scarce Propellant"]) and b["Uses Scarce Propellant"]:
        strict_better = True

    return strict_better


def annotate_drive_obsolescence(
    feat_df: pd.DataFrame,
    care_backup: bool,
    ignore_intraclass: bool,
    class_col: str = "FamilyName",
) -> pd.DataFrame:
    names = feat_df["Name"].tolist()
    n = len(feat_df)
    obsolete_flags: List[bool] = [False] * n
    dominated_by: List[List[str]] = [[] for _ in range(n)]
    dominates_count: List[int] = [0] * n  # how many other drives each row dominates

    for i in range(n):
        row_b = feat_df.iloc[i]
        for j in range(n):
            if i == j:
                continue
            row_a = feat_df.iloc[j]
            if dominates_drive(row_a, row_b, care_backup, ignore_intraclass, class_col):
                # row_a dominates row_b
                obsolete_flags[i] = True
                dominated_by[i].append(row_a["Name"])
                dominates_count[j] += 1  # count domination for the dominating drive

    out = feat_df.copy()
    out["Obsolete"] = obsolete_flags
    out["Dominates (count)"] = dominates_count
    out["Dominated By"] = [", ".join(lst) if lst else "" for lst in dominated_by]

    # Domination Efficiency = Unlock Total Research Cost / Dominates (count)
    if "Unlock Total Research Cost" in feat_df.columns:
        unlock_costs = feat_df["Unlock Total Research Cost"].tolist()
        dom_eff: List[Optional[float]] = []
        for idx in range(n):
            count = dominates_count[idx]
            cost = unlock_costs[idx] if idx < len(unlock_costs) else 0.0
            if count > 0 and cost is not None:
                try:
                    dom_eff.append(float(cost) / float(count))
                except ZeroDivisionError:
                    dom_eff.append(None)
            else:
                dom_eff.append(None)
        out["Domination Efficiency"] = dom_eff

    return out


def dominates_pp(a: pd.Series, b: pd.Series, care_crew: bool) -> bool:
    ge_dims = [
        a["Max Output (GW)"] >= b["Max Output (GW)"],
        a["Efficiency"] >= b["Efficiency"],
        int(a["General Use"]) >= int(b["General Use"]),
    ]
    le_dims = [
        a["Specific Power (tons/GW)"] <= b["Specific Power (tons/GW)"],
    ]
    if care_crew:
        le_dims.append(a["Crew"] <= b["Crew"])

    if not all(ge_dims) or not all(le_dims):
        return False

    strict_better = (
        (a["Max Output (GW)"] > b["Max Output (GW)"])
        or (a["Efficiency"] > b["Efficiency"])
        or (a["Specific Power (tons/GW)"] < b["Specific Power (tons/GW)"])
        or (int(a["General Use"]) > int(b["General Use"]))
    )

    if care_crew and (a["Crew"] < b["Crew"]):
        strict_better = True

    return strict_better



def annotate_pp_obsolescence(feat_df: pd.DataFrame, care_crew: bool) -> pd.DataFrame:
    names = feat_df["Name"].tolist()
    n = len(feat_df)
    obsolete_flags: List[bool] = [False] * n
    dominated_by: List[List[str]] = [[] for _ in range(n)]
    dominates_count: List[int] = [0] * n  # how many other reactors each row dominates

    for i in range(n):
        row_b = feat_df.iloc[i]
        for j in range(n):
            if i == j:
                continue
            row_a = feat_df.iloc[j]
            if dominates_pp(row_a, row_b, care_crew):
                # row_a dominates row_b
                obsolete_flags[i] = True
                dominated_by[i].append(row_a["Name"])
                dominates_count[j] += 1  # count domination for the dominating reactor

    out = feat_df.copy()
    out["Obsolete"] = obsolete_flags
    out["Dominates (count)"] = dominates_count
    out["Dominated By"] = [", ".join(lst) if lst else "" for lst in dominated_by]

    # Domination Efficiency = Unlock Total Research Cost / Dominates (count)
    if "Unlock Total Research Cost" in feat_df.columns:
        unlock_costs = feat_df["Unlock Total Research Cost"].tolist()
        dom_eff: List[Optional[float]] = []
        for idx in range(n):
            count = dominates_count[idx]
            cost = unlock_costs[idx] if idx < len(unlock_costs) else 0.0
            if count > 0 and cost is not None:
                try:
                    dom_eff.append(float(cost) / float(count))
                except ZeroDivisionError:
                    dom_eff.append(None)
            else:
                dom_eff.append(None)
        out["Domination Efficiency"] = dom_eff

    return out


# ---------------------------------------------------------------------------
# Drive + Power Plant compatibility & combos
# ---------------------------------------------------------------------------

def _normalize_class_name(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    if not s:
        return ""
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    return s.lower()


def drive_compatible_with_pp(drive_row: pd.Series, pp_row: pd.Series) -> bool:
    req_raw = drive_row.get("Required Power Plant", "")
    plant_raw = pp_row.get("Class", "")

    req = _normalize_class_name(req_raw)
    plant = _normalize_class_name(plant_raw)

    if not req:
        return True

    if req in ("any", "any_general", "any_reactor", "any_power_plant"):
        return True

    if not plant:
        return False

    if req.startswith("any_"):
        needed = req[len("any_"):]
        if not needed:
            return True
        return (needed == plant) or (needed in plant)

    return (req == plant) or (req in plant)


def build_valid_drive_pp_combos(
    drive_feat: pd.DataFrame,
    pp_feat: pd.DataFrame,
    ref_payload_tons: float,
    ref_propellant_tons: float,
) -> pd.DataFrame:
    if drive_feat is None or pp_feat is None:
        return pd.DataFrame()

    valid_drives = drive_feat[~drive_feat["Obsolete"]]
    valid_plants = pp_feat[~pp_feat["Obsolete"]]

    if valid_drives.empty or valid_plants.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []

    for _, d in valid_drives.iterrows():
        for _, p in valid_plants.iterrows():
            if not drive_compatible_with_pp(d, p):
                continue

            drive_name = d["Name"]
            pp_name = p["Name"]

            thrust = float(d.get("Thrust (N)", 0.0))
            thrust_cap = float(d.get("Combat Thrust Multiplier", 1.0))
            ev_kps = float(d.get("Exhaust Velocity (km/s)", 0.0))
            drive_mass = float(d.get("Drive Mass (tons)", 0.0))
            drive_power = float(d.get("Approx. Drive Power (GW)", 0.0))
            fuel_score = float(d.get("Expensive Fuel Score", 0.0))

            pp_max_output = float(p.get("Max Output (GW)", 0.0))
            pp_spec = float(p.get("Specific Power (tons/GW)", 0.0))

            if pp_max_output <= 0.0 and drive_power > 0.0:
                continue

            if drive_power > 0.0:
                power_ratio = pp_max_output / drive_power
            else:
                power_ratio = float("inf") if pp_max_output > 0.0 else 0.0

            enough_power = pp_max_output >= drive_power if drive_power > 0.0 else True

            if drive_power > 0.0:
                pp_output_used = min(drive_power, pp_max_output)
            else:
                pp_output_used = 0.0

            reactor_mass = pp_output_used * pp_spec

            dry_mass = ref_payload_tons + drive_mass + reactor_mass
            wet_mass = dry_mass + ref_propellant_tons

            if ev_kps > 0.0 and wet_mass > dry_mass > 0.0:
                delta_v_kps = ev_kps * math.log(wet_mass / dry_mass)
            else:
                delta_v_kps = 0.0

            if wet_mass > 0.0:
                accel_cruise_g = thrust / (wet_mass * 1000.0 * 9.81)
                accel_combat_g = (thrust * thrust_cap) / (wet_mass * 1000.0 * 9.81)
            else:
                accel_cruise_g = 0.0
                accel_combat_g = 0.0

            rows.append(
                {
                    "Drive": drive_name,
                    "Drive Propellant": d["Propellant Type"],
                    "Drive Thrust (N)": thrust,
                    "Drive Combat Thrust Multiplier": thrust_cap,
                    "Drive EV (km/s)": ev_kps,
                    "Drive Power (GW)": drive_power,
                    "Drive Mass (tons)": drive_mass,
                    "Drive Expensive Fuel Score": fuel_score,
                    "Requires Power Plant Class": d.get("Required Power Plant", ""),
                    "Power Plant": pp_name,
                    "Power Plant Class": p["Class"],
                    "PP Max Output (GW)": pp_max_output,
                    "PP Specific Power (tons/GW)": pp_spec,
                    "PP Output Used (GW)": pp_output_used,
                    "PP Reactor Mass (tons)": reactor_mass,
                    "Ref Payload Mass (tons)": ref_payload_tons,
                    "Ref Propellant Mass (tons)": ref_propellant_tons,
                    "Ref Dry Mass (tons)": dry_mass,
                    "Ref Wet Mass (tons)": wet_mass,
                    "Total Wet Mass (tons)": wet_mass,
                    "Ref Delta-v (km/s)": delta_v_kps,
                    "Ref Cruise Accel (g)": accel_cruise_g,
                    "Ref Combat Accel (g)": accel_combat_g,
                    "Power Ratio (PP/Drive)": power_ratio,
                    "Reactor Enough Power?": enough_power,
                }
            )

    return pd.DataFrame(rows)


def combo_dominates(a: pd.Series, b: pd.Series) -> bool:
    def get_val(row: pd.Series, col: str, default: float = 0.0) -> float:
        try:
            v = float(row.get(col, default))
            if math.isnan(v):
                return default
            return v
        except Exception:
            return default

    a_dv = get_val(a, "Ref Delta-v (km/s)")
    b_dv = get_val(b, "Ref Delta-v (km/s)")
    a_ac = get_val(a, "Ref Cruise Accel (g)")
    b_ac = get_val(b, "Ref Cruise Accel (g)")
    a_ac2 = get_val(a, "Ref Combat Accel (g)")
    b_ac2 = get_val(b, "Ref Combat Accel (g)")
    a_pr = get_val(a, "Power Ratio (PP/Drive)")
    b_pr = get_val(b, "Power Ratio (PP/Drive)")
    a_cost = get_val(a, "Drive Expensive Fuel Score")
    b_cost = get_val(b, "Drive Expensive Fuel Score")

    ge_dims = [
        a_dv >= b_dv,
        a_ac >= b_ac,
        a_ac2 >= b_ac2,
        a_pr >= b_pr,
    ]
    le_dims = [
        a_cost <= b_cost,
    ]

    if not all(ge_dims) or not all(le_dims):
        return False

    strict_better = (
        (a_dv > b_dv)
        or (a_ac > b_ac)
        or (a_ac2 > b_ac2)
        or (a_pr > b_pr)
        or (a_cost < b_cost)
    )

    return strict_better


def annotate_combo_obsolescence(combos_df: pd.DataFrame) -> pd.DataFrame:
    if combos_df.empty:
        combos_df["Combo Obsolete"] = False
        combos_df["Combo Dominated By"] = ""
        return combos_df

    n = len(combos_df)
    obsolete_flags: List[bool] = [False] * n
    dominated_by: List[List[str]] = [[] for _ in range(n)]

    for i in range(n):
        row_b = combos_df.iloc[i]
        for j in range(n):
            if i == j:
                continue
            row_a = combos_df.iloc[j]
            if combo_dominates(row_a, row_b):
                obsolete_flags[i] = True
                dominated_by[i].append(f"{row_a['Drive']} + {row_a['Power Plant']}")

    out = combos_df.copy()
    out["Combo Obsolete"] = obsolete_flags
    out["Combo Dominated By"] = [
        ", ".join(lst) if lst else "" for lst in dominated_by
    ]
    return out


# ---------------------------------------------------------------------------
# Mission feasibility search
# ---------------------------------------------------------------------------

def mission_feasibility_search(
    combos_df: pd.DataFrame,
    dv_target_kps: float,
    accel_target_g: float,
    accel_type: str = "Combat",
    payload_min: float = 100.0,
    payload_max: float = 300000.0,
    payload_steps: int = 30,
    prop_min: float = 0.0,
    prop_max: float = 20000.0,
    prop_steps: int = 30,
) -> pd.DataFrame:
    if combos_df.empty:
        return pd.DataFrame()

    if dv_target_kps <= 0.0 or accel_target_g <= 0.0:
        return pd.DataFrame()

    if payload_max < payload_min:
        payload_min, payload_max = payload_max, payload_min
    if prop_max < prop_min:
        prop_min, prop_max = prop_max, prop_min

    if payload_steps < 2:
        payload_steps = 2
    if prop_steps < 2:
        prop_steps = 2

    payload_candidates = [
        payload_min + i * (payload_max - payload_min) / (payload_steps - 1)
        for i in range(payload_steps)
    ]
    prop_candidates = [
        prop_min + i * (prop_max - prop_min) / (prop_steps - 1)
        for i in range(prop_steps)
    ]

    g_m_s2 = 9.81
    results: List[Dict[str, Any]] = []

    use_combat = True
    if accel_type:
        use_combat = str(accel_type).lower().startswith("combat")

    for _, row in combos_df.iterrows():
        if not bool(row.get("Reactor Enough Power?", True)):
            continue

        thrust = float(row.get("Drive Thrust (N)", 0.0))
        if thrust <= 0.0:
            continue

        thrust_cap = float(row.get("Drive Combat Thrust Multiplier", 1.0))
        ev_kps = float(row.get("Drive EV (km/s)", 0.0))
        if ev_kps <= 0.0:
            continue

        drive_mass = float(row.get("Drive Mass (tons)", 0.0))
        reactor_mass = float(row.get("PP Reactor Mass (tons)", 0.0))
        m0 = drive_mass + reactor_mass

        t_eff = thrust * thrust_cap if use_combat else thrust
        if t_eff <= 0.0:
            continue

        try:
            k_dv = math.exp(dv_target_kps / ev_kps) - 1.0
        except OverflowError:
            k_dv = float("inf")

        if k_dv < 0.0:
            k_dv = 0.0

        M_max = t_eff / (accel_target_g * 1000.0 * g_m_s2) if accel_target_g > 0.0 else 0.0
        if M_max <= 0.0 or not math.isfinite(k_dv):
            mp_max = 0.0
        else:
            mp_max = M_max / (1.0 + k_dv) - m0
            if mp_max < 0.0:
                mp_max = 0.0

        best_solution = None

        for Mp in payload_candidates:
            m_dry_base = m0 + Mp

            m_wet_max = m_dry_base + prop_max
            if m_wet_max <= m_dry_base:
                continue
            dv_max = ev_kps * math.log(m_wet_max / m_dry_base)
            if dv_max < dv_target_kps:
                continue

            for Mf in prop_candidates:
                if Mf <= 0.0:
                    continue

                m_wet = m_dry_base + Mf

                if m_wet <= m_dry_base:
                    continue
                dv = ev_kps * math.log(m_wet / m_dry_base)
                if dv < dv_target_kps:
                    continue

                accel_g = t_eff / (m_wet * 1000.0 * g_m_s2)
                if accel_g < accel_target_g:
                    continue

                total_wet = m_wet
                if best_solution is None or total_wet < best_solution[2]:
                    best_solution = (Mp, Mf, total_wet, dv, accel_g)

        if best_solution is not None:
            payload_sol, prop_sol, _, dv_sol, accel_sol = best_solution
            results.append(
                {
                    "Drive": row["Drive"],
                    "Power Plant": row["Power Plant"],
                    "Payload Mass (tons)": payload_sol,
                    "Propellant Mass (tons)": prop_sol,
                    "Result Delta-v (km/s)": dv_sol,
                    "Result Accel (g)": accel_sol,
                    "Max Feasible Payload (tons)": mp_max,
                }
            )

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Slider / number input sync callbacks
# ---------------------------------------------------------------------------

def sync_ref_payload_from_slider():
    st.session_state["ref_payload_tons_input"] = st.session_state["ref_payload_tons"]


def sync_ref_payload_from_input():
    st.session_state["ref_payload_tons"] = st.session_state["ref_payload_tons_input"]


def sync_ref_propellant_from_slider():
    st.session_state["ref_propellant_tons_input"] = st.session_state["ref_propellant_tons"]


def sync_ref_propellant_from_input():
    st.session_state["ref_propellant_tons"] = st.session_state["ref_propellant_tons_input"]


def sync_fw_water_from_slider():
    st.session_state["fuel_weight_water_input"] = st.session_state["fuel_weight_water"]


def sync_fw_water_from_input():
    st.session_state["fuel_weight_water"] = st.session_state["fuel_weight_water_input"]


def sync_fw_vol_from_slider():
    st.session_state["fuel_weight_volatiles_input"] = st.session_state["fuel_weight_volatiles"]


def sync_fw_vol_from_input():
    st.session_state["fuel_weight_volatiles"] = st.session_state["fuel_weight_volatiles_input"]


def sync_fw_noble_from_slider():
    st.session_state["fuel_weight_nobleMetals_input"] = st.session_state["fuel_weight_nobleMetals"]


def sync_fw_noble_from_input():
    st.session_state["fuel_weight_nobleMetals"] = st.session_state["fuel_weight_nobleMetals_input"]


def sync_fw_metals_from_slider():
    st.session_state["fuel_weight_metals_input"] = st.session_state["fuel_weight_metals"]


def sync_fw_metals_from_input():
    st.session_state["fuel_weight_metals"] = st.session_state["fuel_weight_metals_input"]


def sync_fw_fissiles_from_slider():
    st.session_state["fuel_weight_fissiles_input"] = st.session_state["fuel_weight_fissiles"]


def sync_fw_fissiles_from_input():
    st.session_state["fuel_weight_fissiles"] = st.session_state["fuel_weight_fissiles_input"]


def sync_fw_antimatter_from_slider():
    st.session_state["fuel_weight_antimatter_input"] = st.session_state["fuel_weight_antimatter"]


def sync_fw_antimatter_from_input():
    st.session_state["fuel_weight_antimatter"] = st.session_state["fuel_weight_antimatter_input"]


def sync_fw_exotics_from_slider():
    st.session_state["fuel_weight_exotics_input"] = st.session_state["fuel_weight_exotics"]


def sync_fw_exotics_from_input():
    st.session_state["fuel_weight_exotics"] = st.session_state["fuel_weight_exotics_input"]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Terra Invicta Propulsion and Power Planner",
        layout="wide",
    )

    # If flagged, scroll to top after actions that change layout a lot
    if st.session_state.get("scroll_to_top", False):
        st.markdown(
            "<script>window.scrollTo(0, 0);</script>",
            unsafe_allow_html=True,
        )
        st.session_state["scroll_to_top"] = False

    # One-time sidebar width initializer: set a wide default once, then let user adjust
    st.markdown(
        """
        <script>
        (function() {
          const KEY = "ti_ppp_sidebar_initialized_v1";
          try {
            const done = window.localStorage.getItem(KEY);
            if (!done) {
              const sidebar = document.querySelector('[data-testid="stSidebar"]');
              if (sidebar) {
                sidebar.style.width = "600px";
                window.localStorage.setItem(KEY, "1");
              }
            }
          } catch (e) {
            console.log("Sidebar init error:", e);
          }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

    st.title("Terra Invicta Propulsion and Power Planner")

    st.markdown(
        textwrap.dedent(
            """
            - Reads **TIDriveTemplate.json** and **TIPowerPlantTemplate.json** from your Terra Invicta install  
            - Starts with **no drives or reactors unlocked**  
            - Unlock **drive families** (e.g. Tungsten Resistojet → all x1..x6)  
            - Obsolescence respects **resource scarcity**, optional
              **backup-power** and **crew size** preferences  
            - Use the sidebar to **download/upload** your profile as JSON  
            - Use the checkboxes next to each table to show/hide columns  
            - Sliders + number inputs control fuel cost weights and reference ship mass,
              feeding into Expensive Fuel Score and combo metrics  
            - Combined table, scatterplot, and mission feasibility are all based on
              valid combos where the reactor has enough power.
            """
        )
    )

    # Load data
    try:
        drive_raw = load_drive_data()
        pp_raw = load_powerplant_data()
        project_raw = load_project_data()

        project_graph = build_project_graph(project_raw)
        project_total_costs = compute_total_project_costs(project_graph)
    except Exception as e:
        st.error(
            "Failed to load Terra Invicta data from the game JSON files.\n\n"
            "The app needs TIDriveTemplate.json and TIPowerPlantTemplate.json.\n\n"
            f"Details:\n{e}"
        )
        return

    backup_col = find_backup_power_column(drive_raw)
    req_pp_col = find_drive_required_pp_column(drive_raw, pp_raw)

    all_drive_families = sorted(drive_raw["FamilyName"].unique())
    all_pp_names = sorted(pp_raw["DisplayName"].unique())

    if "unlocked_drive_families" not in st.session_state:
        st.session_state.unlocked_drive_families = []
    if "unlocked_pp" not in st.session_state:
        st.session_state.unlocked_pp = []

    if "ref_payload_tons" not in st.session_state:
        st.session_state["ref_payload_tons"] = DEFAULT_REF_PAYLOAD_TONS
    if "ref_payload_tons_input" not in st.session_state:
        st.session_state["ref_payload_tons_input"] = st.session_state["ref_payload_tons"]

    if "ref_propellant_tons" not in st.session_state:
        st.session_state["ref_propellant_tons"] = DEFAULT_REF_PROPELLANT_TONS
    if "ref_propellant_tons_input" not in st.session_state:
        st.session_state["ref_propellant_tons_input"] = st.session_state["ref_propellant_tons"]

    if "fuel_weight_water" not in st.session_state:
        st.session_state["fuel_weight_water"] = DEFAULT_FUEL_WEIGHTS["water"]
    if "fuel_weight_water_input" not in st.session_state:
        st.session_state["fuel_weight_water_input"] = st.session_state["fuel_weight_water"]

    if "fuel_weight_volatiles" not in st.session_state:
        st.session_state["fuel_weight_volatiles"] = DEFAULT_FUEL_WEIGHTS["volatiles"]
    if "fuel_weight_volatiles_input" not in st.session_state:
        st.session_state["fuel_weight_volatiles_input"] = st.session_state["fuel_weight_volatiles"]

    if "fuel_weight_nobleMetals" not in st.session_state:
        st.session_state["fuel_weight_nobleMetals"] = DEFAULT_FUEL_WEIGHTS["nobleMetals"]
    if "fuel_weight_nobleMetals_input" not in st.session_state:
        st.session_state["fuel_weight_nobleMetals_input"] = st.session_state["fuel_weight_nobleMetals"]

    if "fuel_weight_metals" not in st.session_state:
        st.session_state["fuel_weight_metals"] = DEFAULT_FUEL_WEIGHTS["metals"]
    if "fuel_weight_metals_input" not in st.session_state:
        st.session_state["fuel_weight_metals_input"] = st.session_state["fuel_weight_metals"]

    if "fuel_weight_fissiles" not in st.session_state:
        st.session_state["fuel_weight_fissiles"] = DEFAULT_FUEL_WEIGHTS["fissiles"]
    if "fuel_weight_fissiles_input" not in st.session_state:
        st.session_state["fuel_weight_fissiles_input"] = st.session_state["fuel_weight_fissiles"]

    if "fuel_weight_antimatter" not in st.session_state:
        st.session_state["fuel_weight_antimatter"] = DEFAULT_FUEL_WEIGHTS["antimatter"]
    if "fuel_weight_antimatter_input" not in st.session_state:
        st.session_state["fuel_weight_antimatter_input"] = st.session_state["fuel_weight_antimatter"]

    if "fuel_weight_exotics" not in st.session_state:
        st.session_state["fuel_weight_exotics"] = DEFAULT_FUEL_WEIGHTS["exotics"]
    if "fuel_weight_exotics_input" not in st.session_state:
        st.session_state["fuel_weight_exotics_input"] = st.session_state["fuel_weight_exotics"]

    if "accel_in_milligees" not in st.session_state:
        st.session_state["accel_in_milligees"] = False

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    st.sidebar.subheader("Help")
    st.sidebar.download_button(
        "Download help file",
        data=HELP_HTML,
        file_name="ti_propulsion_power_planner_help.html",
        mime="text/html",
        key="btn_help_download",
    )

    st.sidebar.header("Profile")

    profile_dict = build_profile_dict()
    st.sidebar.download_button(
        "Download profile JSON",
        data=json.dumps(profile_dict, indent=2),
        file_name="ti_propulsion_power_planner_profile.json",
        mime="application/json",
        key="btn_download_profile",
    )

    uploaded_profile = st.sidebar.file_uploader(
        "Upload profile JSON", type=["json"], key="profile_uploader"
    )
    if uploaded_profile is not None:
        try:
            file_bytes = uploaded_profile.getvalue()
            if file_bytes:
                file_hash = hashlib.md5(file_bytes).hexdigest()
                last_hash = st.session_state.get("last_uploaded_profile_hash")

                if last_hash != file_hash:
                    max_profile_for_limit = {
                        "unlocked_drive_families": all_drive_families,
                        "unlocked_pp": all_pp_names,
                        "resource_abundance": {
                            "water": True,
                            "volatiles": True,
                            "metals": True,
                            "nobleMetals": True,
                            "fissiles": True,
                            "antimatter": True,
                            "exotics": True,
                        },
                        "care_backup": True,
                        "care_crew": True,
                        "ref_payload_tons": 300000.0,
                        "ref_propellant_tons": 300000.0,
                        "fuel_weights": {
                            "water": 10.0,
                            "volatiles": 10.0,
                            "metals": 10.0,
                            "nobleMetals": 10.0,
                            "fissiles": 20.0,
                            "antimatter": 50.0,
                            "exotics": 50.0,
                        },
                        "ignore_intraclass": True,
                        "accel_in_milligees": True,
                    }
                    max_profile_json = json.dumps(max_profile_for_limit, indent=2)
                    max_profile_bytes = len(max_profile_json.encode("utf-8"))
                    size_limit_bytes = max_profile_bytes + 1024

                    if len(file_bytes) > size_limit_bytes:
                        st.sidebar.error(
                            f"Profile file is too large (> {size_limit_bytes} bytes). "
                            "This does not look like a valid profile."
                        )
                    else:
                        try:
                            profile_data = json.loads(file_bytes.decode("utf-8"))
                        except Exception as e:
                            st.sidebar.error(f"Invalid JSON profile: {e}")
                        else:
                            try:
                                sanitized = sanitize_profile_dict(
                                    profile_data,
                                    all_drive_families=all_drive_families,
                                    all_pp_names=all_pp_names,
                                )
                            except Exception as e:
                                st.sidebar.error(f"Profile failed validation: {e}")
                            else:
                                apply_profile(sanitized)
                                st.session_state["last_uploaded_profile_hash"] = file_hash
                                st.sidebar.success("Profile applied from uploaded JSON.")
        except Exception as e:
            st.sidebar.error(f"Failed to load uploaded profile: {e}")

    st.sidebar.header("Global Settings")

    st.sidebar.subheader("Resource abundance (for drives)")

    resource_abundance: Dict[str, bool] = {}
    resource_abundance["water"] = st.sidebar.checkbox(
        "Water abundant",
        value=st.session_state.get("water_abundant", True),
        key="water_abundant",
    )
    resource_abundance["volatiles"] = st.sidebar.checkbox(
        "Volatiles abundant",
        value=st.session_state.get("volatiles_abundant", True),
        key="volatiles_abundant",
    )
    resource_abundance["metals"] = st.sidebar.checkbox(
        "Base metals abundant",
        value=st.session_state.get("metals_abundant", True),
        key="metals_abundant",
    )
    resource_abundance["nobleMetals"] = st.sidebar.checkbox(
        "Noble metals abundant",
        value=st.session_state.get("nobleMetals_abundant", True),
        key="nobleMetals_abundant",
    )
    resource_abundance["fissiles"] = st.sidebar.checkbox(
        "Fissiles abundant",
        value=st.session_state.get("fissiles_abundant", True),
        key="fissiles_abundant",
    )
    resource_abundance["antimatter"] = st.sidebar.checkbox(
        "Antimatter abundant",
        value=st.session_state.get("antimatter_abundant", True),
        key="antimatter_abundant",
    )
    resource_abundance["exotics"] = st.sidebar.checkbox(
        "Exotics abundant",
        value=st.session_state.get("exotics_abundant", True),
        key="exotics_abundant",
    )

    st.sidebar.subheader("Optional obsolescence parameters")

    if find_backup_power_column(drive_raw):
        care_backup = st.sidebar.checkbox(
            "Care about drives that provide backup power when idle",
            value=st.session_state.get("care_backup", True),
            key="care_backup",
        )
    else:
        st.sidebar.info(
            "Backup‑power column not detected; backup‑power preference is disabled."
        )
        st.session_state["care_backup"] = False
        care_backup = False

    care_crew = st.sidebar.checkbox(
        "Care about crew size",
        value=st.session_state.get("care_crew", False),
        key="care_crew",
    )

    st.sidebar.subheader("Drive dominance options")
    ignore_intraclass = st.sidebar.checkbox(
        "Don’t mark drives obsolete within the same family/class",
        value=st.session_state.get("ignore_intraclass", False),
        key="ignore_intraclass",
    )

    hide_dominated = st.sidebar.checkbox(
        "Hide dominated combos (combo-level obsolete)",
        value=st.session_state.get("hide_combo_obsolete", True),
        key="hide_combo_obsolete",
    )

    st.sidebar.subheader("Fuel cost weights")

    fw_water_cols = st.sidebar.columns([2, 1])
    with fw_water_cols[0]:
        st.slider(
            "Water weight",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_water",
            on_change=sync_fw_water_from_slider,
        )
    with fw_water_cols[1]:
        st.number_input(
            "Exact",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_water_input",
            on_change=sync_fw_water_from_input,
        )

    fw_vol_cols = st.sidebar.columns([2, 1])
    with fw_vol_cols[0]:
        st.slider(
            "Volatiles weight",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_volatiles",
            on_change=sync_fw_vol_from_slider,
        )
    with fw_vol_cols[1]:
        st.number_input(
            "Exact ",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_volatiles_input",
            on_change=sync_fw_vol_from_input,
        )

    fw_noble_cols = st.sidebar.columns([2, 1])
    with fw_noble_cols[0]:
        st.slider(
            "Noble metals weight",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_nobleMetals",
            on_change=sync_fw_noble_from_slider,
        )
    with fw_noble_cols[1]:
        st.number_input(
            "Exact  ",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_nobleMetals_input",
            on_change=sync_fw_noble_from_input,
        )

    fw_metals_cols = st.sidebar.columns([2, 1])
    with fw_metals_cols[0]:
        st.slider(
            "Base metals weight",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_metals",
            on_change=sync_fw_metals_from_slider,
        )
    with fw_metals_cols[1]:
        st.number_input(
            "Exact   ",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="fuel_weight_metals_input",
            on_change=sync_fw_metals_from_input,
        )

    fw_fiss_cols = st.sidebar.columns([2, 1])
    with fw_fiss_cols[0]:
        st.slider(
            "Fissiles weight",
            min_value=0.0,
            max_value=20.0,
            step=0.5,
            key="fuel_weight_fissiles",
            on_change=sync_fw_fissiles_from_slider,
        )
    with fw_fiss_cols[1]:
        st.number_input(
            "Exact    ",
            min_value=0.0,
            max_value=20.0,
            step=0.5,
            key="fuel_weight_fissiles_input",
            on_change=sync_fw_fissiles_from_input,
        )

    fw_anti_cols = st.sidebar.columns([2, 1])
    with fw_anti_cols[0]:
        st.slider(
            "Antimatter weight",
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            key="fuel_weight_antimatter",
            on_change=sync_fw_antimatter_from_slider,
        )
    with fw_anti_cols[1]:
        st.number_input(
            "Exact     ",
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            key="fuel_weight_antimatter_input",
            on_change=sync_fw_antimatter_from_input,
        )

    fw_exo_cols = st.sidebar.columns([2, 1])
    with fw_exo_cols[0]:
        st.slider(
            "Exotics weight",
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            key="fuel_weight_exotics",
            on_change=sync_fw_exotics_from_slider,
        )
    with fw_exo_cols[1]:
        st.number_input(
            "Exact      ",
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            key="fuel_weight_exotics_input",
            on_change=sync_fw_exotics_from_input,
        )

    fuel_weight_water = float(st.session_state["fuel_weight_water"])
    fuel_weight_volatiles = float(st.session_state["fuel_weight_volatiles"])
    fuel_weight_nobleMetals = float(st.session_state["fuel_weight_nobleMetals"])
    fuel_weight_metals = float(st.session_state["fuel_weight_metals"])
    fuel_weight_fissiles = float(st.session_state["fuel_weight_fissiles"])
    fuel_weight_antimatter = float(st.session_state["fuel_weight_antimatter"])
    fuel_weight_exotics = float(st.session_state["fuel_weight_exotics"])

    fuel_weights = {
        "water": fuel_weight_water,
        "volatiles": fuel_weight_volatiles,
        "metals": fuel_weight_metals,
        "nobleMetals": fuel_weight_nobleMetals,
        "fissiles": fuel_weight_fissiles,
        "antimatter": fuel_weight_antimatter,
        "exotics": fuel_weight_exotics,
    }

    st.sidebar.subheader("Reference ship (for Δv / accel)")

    ref_payload_cols = st.sidebar.columns([2, 1])
    with ref_payload_cols[0]:
        st.slider(
            "Reference payload mass (tons)",
            min_value=100.0,
            max_value=300000.0,
            step=100.0,
            key="ref_payload_tons",
            on_change=sync_ref_payload_from_slider,
        )
    with ref_payload_cols[1]:
        st.number_input(
            "Exact    ",
            min_value=100.0,
            max_value=300000.0,
            step=100.0,
            key="ref_payload_tons_input",
            on_change=sync_ref_payload_from_input,
        )

    ref_prop_cols = st.sidebar.columns([2, 1])
    with ref_prop_cols[0]:
        st.slider(
            "Reference propellant mass (tons)",
            min_value=0.0,
            max_value=300000.0,
            step=100.0,
            key="ref_propellant_tons",
            on_change=sync_ref_propellant_from_slider,
        )
    with ref_prop_cols[1]:
        st.number_input(
            "Exact     ",
            min_value=0.0,
            max_value=300000.0,
            step=100.0,
            key="ref_propellant_tons_input",
            on_change=sync_ref_propellant_from_input,
        )

    ref_payload_tons = float(st.session_state["ref_payload_tons"])
    ref_propellant_tons = float(st.session_state["ref_propellant_tons"])

    st.sidebar.subheader("Display options")
    accel_in_milligees = st.sidebar.checkbox(
        "Display accelerations in milligees",
        value=st.session_state.get("accel_in_milligees", False),
        key="accel_in_milligees",
    )

    st.sidebar.caption(
        "Game data is read from TIDriveTemplate.json and TIPowerPlantTemplate.json "
        "in your Terra Invicta installation (see help for search order). "
        "Use the buttons above to download/upload your profile JSON."
    )

    # -----------------------------------------------------------------------
    # Unlocked content
    # -----------------------------------------------------------------------
    st.subheader("Unlocked Content")

    col_d, col_p = st.columns(2)

    with col_d:
        st.markdown("### Drives (families)")

        search_drive = st.text_input("Search drive families to unlock", key="search_drives")
        unlocked_drive_families = st.session_state.unlocked_drive_families

        filtered_options = [
            name for name in all_drive_families
            if name not in unlocked_drive_families and search_drive.lower() in name.lower()
        ]
        add_drive_choice = st.selectbox(
            "Select drive family to unlock",
            ["-- Select drive family --"] + filtered_options,
            key="add_drive_choice",
        )
        add_cols = st.columns(3)
        with add_cols[0]:
            if st.button("Add Drive Family", key="btn_add_drive"):
                if (
                    add_drive_choice != "-- Select drive family --"
                    and add_drive_choice not in st.session_state.unlocked_drive_families
                ):
                    st.session_state.unlocked_drive_families.append(add_drive_choice)
                    st.session_state["scroll_to_top"] = True
        with add_cols[1]:
            if st.button("Unlock ALL drive families", key="btn_unlock_all_drives"):
                st.session_state.unlocked_drive_families = list(all_drive_families)
                st.session_state["scroll_to_top"] = True
        with add_cols[2]:
            if st.button("Clear all drives", key="btn_clear_drives"):
                st.session_state.unlocked_drive_families = []
                st.session_state["scroll_to_top"] = True

        unlocked_drive_families = st.session_state.unlocked_drive_families
        st.write(f"Unlocked drive families: **{len(unlocked_drive_families)}**")
        if unlocked_drive_families:
            st.table(pd.DataFrame({"Unlocked Drive Families": unlocked_drive_families}))

        if unlocked_drive_families:
            to_remove = st.multiselect(
                "Remove selected drive families",
                unlocked_drive_families,
                key="remove_drives_multi",
            )
            if st.button("Remove Drive Families", key="btn_remove_drives"):
                st.session_state.unlocked_drive_families = [
                    d for d in unlocked_drive_families if d not in to_remove
                ]
                st.session_state["scroll_to_top"] = True

    with col_p:
        st.markdown("### Power Plants")

        search_pp = st.text_input("Search reactors to unlock", key="search_pp")
        unlocked_pp = st.session_state.unlocked_pp

        filtered_pp_options = [
            name for name in all_pp_names
            if name not in unlocked_pp and search_pp.lower() in name.lower()
        ]
        add_pp_choice = st.selectbox(
            "Select reactor to unlock",
            ["-- Select reactor --"] + filtered_pp_options,
            key="add_pp_choice",
        )
        pp_cols = st.columns(3)
        with pp_cols[0]:
            if st.button("Add Reactor", key="btn_add_pp"):
                if add_pp_choice != "-- Select reactor --" and add_pp_choice not in st.session_state.unlocked_pp:
                    st.session_state.unlocked_pp.append(add_pp_choice)
                    st.session_state["scroll_to_top"] = True
        with pp_cols[1]:
            if st.button("Unlock ALL reactors", key="btn_unlock_all_pp"):
                st.session_state.unlocked_pp = list(all_pp_names)
                st.session_state["scroll_to_top"] = True
        with pp_cols[2]:
            if st.button("Clear all reactors", key="btn_clear_pp"):
                st.session_state.unlocked_pp = []
                st.session_state["scroll_to_top"] = True

        unlocked_pp = st.session_state.unlocked_pp
        st.write(f"Unlocked power plants: **{len(unlocked_pp)}**")
        if unlocked_pp:
            st.table(pd.DataFrame({"Unlocked Power Plants": unlocked_pp}))

        if unlocked_pp:
            to_remove_pp = st.multiselect(
                "Remove selected reactors",
                unlocked_pp,
                key="remove_pp_multi",
            )
            if st.button("Remove Reactors", key="btn_remove_pp"):
                st.session_state.unlocked_pp = [
                    p for p in unlocked_pp if p not in to_remove_pp
                ]
                st.session_state["scroll_to_top"] = True

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Precompute feature tables
    # -----------------------------------------------------------------------
    unlocked_drive_families = st.session_state.unlocked_drive_families
    drive_filtered = drive_raw[drive_raw["FamilyName"].isin(unlocked_drive_families)]

    if drive_filtered.empty:
        drive_feat = None
    else:
        drive_feat = build_drive_features(
            drive_filtered,
            resource_abundance,
            backup_col=find_backup_power_column(drive_raw),
            req_pp_col=find_drive_required_pp_column(drive_raw, pp_raw),
            fuel_weights=fuel_weights,
            project_total_costs=project_total_costs,
        )
        drive_feat = annotate_drive_obsolescence(
            drive_feat, care_backup, ignore_intraclass, class_col="FamilyName"
        )

    unlocked_pp_names = st.session_state.unlocked_pp
    pp_filtered = pp_raw[pp_raw["DisplayName"].isin(unlocked_pp_names)]

    if pp_filtered.empty:
        pp_feat = None
    else:
        pp_feat = build_pp_features(pp_filtered, project_total_costs=project_total_costs)
        pp_feat = annotate_pp_obsolescence(pp_feat, care_crew=care_crew)

    # -----------------------------------------------------------------------
    # Tabs: Drives & Power Plants
    # -----------------------------------------------------------------------
    tab_drives, tab_pp_tab = st.tabs(["🚀 Drives", "⚡ Power Plants"])

    with tab_drives:
        st.header("Drive Obsolescence")

        if drive_feat is None:
            st.info(
                "No drives unlocked yet. Add some drive families in the "
                "'Unlocked Content' panel above."
            )
        else:
            total = len(drive_feat)
            obsolete_count = int(drive_feat["Obsolete"].sum())
            st.write(
                f"Unlocked drive modules (variants): **{total}**, "
                f"Obsolete (dominated): **{obsolete_count}**"
            )

            base_cols = ["Name", "Obsolete", "Dominates (count)", "Dominated By"]
            drive_property_cols = [c for c in drive_feat.columns if c not in base_cols]

            default_drive_props_selected = {
                "Expensive Fuel Score",
                "Uses Scarce Propellant",
                "Backup Power Mode",
                "Per-Tank Propellant Mix",
            }

            if "drive_visible_props" not in st.session_state:
                st.session_state.drive_visible_props = {
                    c: (c in default_drive_props_selected) for c in drive_property_cols
                }

            left_col, right_col = st.columns([1, 4])

            with left_col:
                st.markdown("**Drive columns**")
                visible_props = []
                for c in drive_property_cols:
                    # Use a stable, safe widget key derived from the column name
                    # to avoid collisions or mis-wiring when column labels change.
                    safe_key = hashlib.md5(c.encode("utf-8")).hexdigest()
                    key = f"drive_col_{safe_key}"
                    default_val = st.session_state.drive_visible_props.get(
                        c, c in default_drive_props_selected
                    )
                    val = st.checkbox(c, value=default_val, key=key)
                    st.session_state.drive_visible_props[c] = val
                    if val:
                        visible_props.append(c)

            with right_col:
                cols_to_show = [c for c in base_cols if c in drive_feat.columns] + [
                    c for c in visible_props if c in drive_feat.columns
                ]
                df_to_show = drive_feat.loc[:, cols_to_show]

                sort_order = ["Obsolete", "FamilyName", "Propellant Type", "Thrust (N)"]
                asc_map = {
                    "Obsolete": True,
                    "FamilyName": True,
                    "Propellant Type": True,
                    "Thrust (N)": False,
                }
                sort_keys_existing = [c for c in sort_order if c in df_to_show.columns]
                if sort_keys_existing:
                    ascending = [asc_map[c] for c in sort_keys_existing]
                    df_sorted = df_to_show.sort_values(
                        sort_keys_existing, ascending=ascending
                    )
                else:
                    df_sorted = df_to_show

                key_seed = f"{cols_to_show}|{df_sorted.shape[0]}|{df_sorted.shape[1]}"
                df_key = "df_drives_" + hashlib.md5(key_seed.encode("utf-8")).hexdigest()

                st.dataframe(
                    df_sorted,
                    use_container_width=True,
                    key=df_key,
                )

    with tab_pp_tab:
        st.header("Power Plant Obsolescence")

        if pp_feat is None:
            st.info(
                "No power plants unlocked yet. Add some in the "
                "'Unlocked Content' panel above."
            )
        else:
            total = len(pp_feat)
            obsolete_count = int(pp_feat["Obsolete"].sum())
            st.write(
                f"Unlocked power plants: **{total}**, "
                f"Obsolete (dominated): **{obsolete_count}**"
            )

            base_cols = ["Name", "Obsolete", "Dominates (count)", "Dominated By"]
            pp_property_cols = [c for c in pp_feat.columns if c not in base_cols]

            if "pp_visible_props" not in st.session_state:
                st.session_state.pp_visible_props = {
                    c: True for c in pp_property_cols
                }

            left_col, right_col = st.columns([1, 4])

            with left_col:
                st.markdown("**Reactor columns**")
                visible_props_pp = []
                for c in pp_property_cols:
                    # Use a stable, safe widget key derived from the column name
                    # to avoid collisions or mis-wiring when column labels change.
                    safe_key = hashlib.md5(c.encode("utf-8")).hexdigest()
                    key = f"pp_col_{safe_key}"
                    default_val = st.session_state.pp_visible_props.get(c, True)
                    val = st.checkbox(c, value=default_val, key=key)
                    st.session_state.pp_visible_props[c] = val
                    if val:
                        visible_props_pp.append(c)

            with right_col:
                cols_to_show_pp = [c for c in base_cols if c in pp_feat.columns] + [
                    c for c in visible_props_pp if c in pp_feat.columns
                ]
                df_to_show_pp = pp_feat.loc[:, cols_to_show_pp]

                sort_order_pp = ["Obsolete", "Class", "Max Output (GW)"]
                asc_map_pp = {
                    "Obsolete": True,
                    "Class": True,
                    "Max Output (GW)": False,
                }
                sort_keys_existing_pp = [
                    c for c in sort_order_pp if c in df_to_show_pp.columns
                ]
                if sort_keys_existing_pp:
                    ascending_pp = [asc_map_pp[c] for c in sort_keys_existing_pp]
                    df_sorted_pp = df_to_show_pp.sort_values(
                        sort_keys_existing_pp, ascending=ascending_pp
                    )
                else:
                    df_sorted_pp = df_to_show_pp

                key_seed_pp = (
                    f"{cols_to_show_pp}|{df_sorted_pp.shape[0]}|{df_sorted_pp.shape[1]}"
                )
                df_key_pp = (
                    "df_pp_" + hashlib.md5(key_seed_pp.encode("utf-8")).hexdigest()
                )

                st.dataframe(
                    df_sorted_pp,
                    use_container_width=True,
                    key=df_key_pp,
                )

    # -----------------------------------------------------------------------
    # Combined combos section
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Valid Drive + Power Plant combinations (non‑obsolete, enough power)")

    if (drive_feat is None) or (pp_feat is None):
        st.info(
            "Need at least one unlocked drive family and one unlocked power plant "
            "to compute combinations."
        )
    else:
        combos_all = build_valid_drive_pp_combos(
            drive_feat, pp_feat, ref_payload_tons, ref_propellant_tons
        )

        if "Reactor Enough Power?" in combos_all.columns:
            combos_df_base = combos_all[combos_all["Reactor Enough Power?"]].copy()
        else:
            combos_df_base = combos_all.copy()

        if combos_df_base.empty:
            st.info(
                "No valid combinations found among the current non‑obsolete drives "
                "and power plants that have enough reactor power."
            )
        else:
            combos_df = annotate_combo_obsolescence(combos_df_base)

            base_combo_cols = ["Drive", "Power Plant"]
            combo_prop_cols = [
                c
                for c in combos_df.columns
                if c not in base_combo_cols and c not in ("Combo Obsolete", "Combo Dominated By")
            ]

            default_combo_props_selected = {
                "Drive Expensive Fuel Score",
            }

            if "combo_visible_props" not in st.session_state:
                st.session_state.combo_visible_props = {
                    c: (c in default_combo_props_selected) for c in combo_prop_cols
                }

            hide_dominated_flag = st.session_state.get("hide_combo_obsolete", True)
            if hide_dominated_flag and "Combo Obsolete" in combos_df.columns:
                combos_listing = combos_df[~combos_df["Combo Obsolete"]].copy()
            else:
                combos_listing = combos_df.copy()

            # For computations (mission search), use combos_listing in g units
            combos_for_feas = combos_listing

            # For display (tables / scatter), we may scale accelerations
            combos_display = combos_listing.copy()
            if accel_in_milligees:
                for col in ["Ref Cruise Accel (g)", "Ref Combat Accel (g)"]:
                    if col in combos_display.columns:
                        combos_display[col] = combos_display[col] * 1000.0

            c_left, c_right = st.columns([1, 4])

            with c_left:
                st.markdown("**Combo table columns**")
                visible_combo_props = []
                for c in combo_prop_cols:
                    key = f"combo_col_{c}"
                    default_val = st.session_state.combo_visible_props.get(
                        c, c in default_combo_props_selected
                    )
                    val = st.checkbox(c, value=default_val, key=key)
                    st.session_state.combo_visible_props[c] = val
                    if val:
                        visible_combo_props.append(c)

            with c_right:
                cols_to_show_combo = [
                    c for c in base_combo_cols if c in combos_display.columns
                ] + [c for c in visible_combo_props if c in combos_display.columns]

                df_combo = combos_display.loc[:, cols_to_show_combo]

                sort_order_combo = ["Drive", "Power Plant", "Ref Delta-v (km/s)"]
                asc_map_combo = {
                    "Drive": True,
                    "Power Plant": True,
                    "Ref Delta-v (km/s)": False,
                }
                sort_keys_existing_combo = [
                    c for c in sort_order_combo if c in df_combo.columns
                ]
                if sort_keys_existing_combo:
                    ascending_combo = [
                        asc_map_combo[c] for c in sort_keys_existing_combo
                    ]
                    df_combo_sorted = df_combo.sort_values(
                        sort_keys_existing_combo, ascending=ascending_combo
                    )
                else:
                    df_combo_sorted = df_combo

                # Rename accel columns for display if using milligees
                if accel_in_milligees:
                    df_combo_sorted = df_combo_sorted.rename(
                        columns={
                            "Ref Cruise Accel (g)": "Ref Cruise Accel (milli-g)",
                            "Ref Combat Accel (g)": "Ref Combat Accel (milli-g)",
                        }
                    )

                key_seed_combo = (
                    f"{cols_to_show_combo}|"
                    f"{df_combo_sorted.shape[0]}|{df_combo_sorted.shape[1]}"
                )
                df_key_combo = (
                    "df_combos_"
                    + hashlib.md5(key_seed_combo.encode("utf-8")).hexdigest()
                )

                st.dataframe(
                    df_combo_sorted,
                    use_container_width=True,
                    key=df_key_combo,
                )

            # ------------------- Scatterplot -------------------
            st.markdown("### Scatterplot of valid combinations")

            # Map display labels to underlying column names (units handled via label text)
            scatter_cols = {}

            # Expensive fuel score & wet mass & power ratio independent of units
            if "Drive Expensive Fuel Score" in combos_display.columns:
                scatter_cols["Drive Expensive Fuel Score"] = "Drive Expensive Fuel Score"
            if "Ref Delta-v (km/s)" in combos_display.columns:
                scatter_cols["Ref Delta-v (km/s)"] = "Ref Delta-v (km/s)"
            if "Power Ratio (PP/Drive)" in combos_display.columns:
                scatter_cols["Power Ratio (PP/Drive)"] = "Power Ratio (PP/Drive)"
            if "Total Wet Mass (tons)" in combos_display.columns:
                scatter_cols["Total Wet Mass (tons)"] = "Total Wet Mass (tons)"

            # Accel labels depend on display units
            if "Ref Cruise Accel (g)" in combos_display.columns:
                label_cruise = "Ref Cruise Accel (milli-g)" if accel_in_milligees else "Ref Cruise Accel (g)"
                scatter_cols[label_cruise] = "Ref Cruise Accel (g)"
            if "Ref Combat Accel (g)" in combos_display.columns:
                label_combat = "Ref Combat Accel (milli-g)" if accel_in_milligees else "Ref Combat Accel (g)"
                scatter_cols[label_combat] = "Ref Combat Accel (g)"

            if len(scatter_cols) < 2:
                st.info(
                    "Not enough numeric metrics available for scatterplot "
                    "(need at least two of the configured columns)."
                )
            else:
                labels = list(scatter_cols.keys())

                # choose defaults: Cruise accel on X, Delta-v on Y if available
                default_x_label = None
                default_y_label = None

                for lbl in labels:
                    if lbl.startswith("Ref Cruise Accel"):
                        default_x_label = lbl
                    if lbl.startswith("Ref Delta-v"):
                        default_y_label = lbl

                if default_x_label is None:
                    default_x_label = labels[0]
                if default_y_label is None:
                    default_y_label = labels[1] if len(labels) > 1 else labels[0]

                col_x, col_y = st.columns(2)
                with col_x:
                    x_label = st.selectbox(
                        "X axis",
                        labels,
                        index=labels.index(default_x_label),
                        key="scatter_x",
                    )
                with col_y:
                    y_label = st.selectbox(
                        "Y axis",
                        labels,
                        index=labels.index(default_y_label),
                        key="scatter_y",
                    )

                if x_label == y_label:
                    st.info(
                        "X and Y axes are the same; select different metrics "
                        "to see a scatterplot."
                    )
                else:
                    x_col = scatter_cols[x_label]
                    y_col = scatter_cols[y_label]

                    scatter_data = combos_display[
                        ["Drive", "Power Plant", x_col, y_col]
                    ].dropna()

                    if scatter_data.empty:
                        st.info("No data points available for the selected axes.")
                    else:
                        chart = (
                            alt.Chart(scatter_data)
                            .mark_point()
                            .encode(
                                x=alt.X(x_col, title=x_label),
                                y=alt.Y(y_col, title=y_label),
                                tooltip=[
                                    alt.Tooltip("Drive", title="Drive"),
                                    alt.Tooltip("Power Plant", title="Power Plant"),
                                    alt.Tooltip(x_col, title=x_label),
                                    alt.Tooltip(y_col, title=y_label),
                                ],
                            )
                            .interactive()
                        )
                        st.altair_chart(chart, use_container_width=True)

            # ------------------- Mission Feasibility -------------------
            st.markdown("---")
            st.markdown("### Mission feasibility search")

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                dv_target = st.number_input(
                    "Target Δv (km/s)",
                    min_value=0.0,
                    value=float(st.session_state.get("mission_dv_target", 30.0)),
                    step=1.0,
                    key="mission_dv_target",
                )
            with col_m2:
                accel_type_label = st.selectbox(
                    "Acceleration constraint",
                    ["Combat acceleration (g)", "Cruise acceleration (g)"],
                    key="mission_accel_type",
                )
            with col_m3:
                accel_default = (
                    float(st.session_state.get("mission_accel_target", 0.05))
                    if "mission_accel_target" in st.session_state
                    else (0.01 if accel_type_label.startswith("Cruise") else 0.05)
                )
                accel_target = st.number_input(
                    "Target acceleration (g)",
                    min_value=0.0,
                    value=accel_default,
                    step=0.001,
                    format="%.3f",
                    key="mission_accel_target",
                )
            with col_m4:
                min_payload = st.number_input(
                    "Minimum payload mass (tons)",
                    min_value=0.0,
                    max_value=300000.0,
                    value=float(st.session_state.get("mission_min_payload", 100.0)),
                    step=100.0,
                    key="mission_min_payload",
                )

            accel_type = "Combat" if accel_type_label.startswith("Combat") else "Cruise"

            if st.button("Calculate mission feasibility", key="btn_mission_feasibility"):
                if dv_target <= 0.0 or accel_target <= 0.0:
                    st.warning(
                        "Please enter positive values for both Δv and acceleration."
                    )
                else:
                    feas_df = mission_feasibility_search(
                        combos_for_feas,
                        dv_target_kps=dv_target,
                        accel_target_g=accel_target,
                        accel_type=accel_type,
                        payload_min=min_payload,
                        payload_max=300000.0,
                        payload_steps=30,
                        prop_min=0.0,
                        prop_max=20000.0,
                        prop_steps=30,
                    )

                    if feas_df.empty:
                        st.warning(
                            "No Drive + Power Plant combinations could meet these "
                            "targets within the search ranges."
                        )
                    else:
                        st.success(
                            f"{len(feas_df)} combinations can meet the mission "
                            "targets at some payload/propellant mass."
                        )
                        feas_sorted = feas_df.sort_values(
                            ["Drive", "Power Plant"]
                        ).reset_index(drop=True)

                        # Scale accel if in milligees for display
                        feas_display = feas_sorted.copy()
                        if accel_in_milligees and "Result Accel (g)" in feas_display.columns:
                            feas_display["Result Accel (g)"] = feas_display["Result Accel (g)"] * 1000.0
                            feas_display = feas_display.rename(
                                columns={"Result Accel (g)": "Result Accel (milli-g)"}
                            )

                        key_seed_feas = (
                            f"{feas_display.shape[0]}|{feas_display.shape[1]}"
                        )
                        df_key_feas = (
                            "df_mission_feas_"
                            + hashlib.md5(key_seed_feas.encode("utf-8")).hexdigest()
                        )

                        st.dataframe(
                            feas_display,
                            use_container_width=True,
                            key=df_key_feas,
                        )


if __name__ == "__main__":
    main()
