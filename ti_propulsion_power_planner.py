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
        - Additional Possible Payload (tons)

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
  <title>Terra Invicta Propulsion &amp; Power Planner — Help</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, sans-serif;
      line-height: 1.6;
      margin: 2rem auto;
      max-width: 800px;
      padding: 0 1rem;
      color: #333;
    }
    h1 { color: #1a1a1a; margin-bottom: 0.5rem; }
    h2 { color: #2c3e50; margin-top: 2rem; border-bottom: 2px solid #eee; padding-bottom: 0.3rem; }
    h3 { color: #34495e; margin-top: 1.5rem; }
    code {
      font-family: "Consolas", "Monaco", "Courier New", monospace;
      background: #f4f4f4;
      padding: 0.2em 0.4em;
      border-radius: 3px;
      font-size: 0.9em;
    }
    pre {
      background: #f8f8f8;
      padding: 1rem;
      border-radius: 5px;
      overflow-x: auto;
      border-left: 3px solid #3498db;
    }
    ul { margin-left: 1.5rem; }
    li { margin-bottom: 0.5rem; }
    .intro { font-size: 1.1em; color: #555; margin-bottom: 1.5rem; }
    .tip {
      background: #e8f4f8;
      padding: 1rem;
      border-left: 4px solid #3498db;
      margin: 1rem 0;
      border-radius: 3px;
    }
  </style>
</head>
<body>
  <h1>Terra Invicta Propulsion &amp; Power Planner</h1>
  <p class="intro">
    A tool for analyzing ship drives and power plants in <strong>Terra Invicta</strong>. 
    Identify obsolete (dominated) drives and reactors, explore valid combinations, 
    and find feasible designs for mission requirements.
  </p>

  <h2>Quick Start</h2>
  <ol>
    <li><strong>Unlock drives and reactors</strong> — Start by unlocking drive families and power plants</li>
    <li><strong>Set resource abundance</strong> — Mark which resources are plentiful in your campaign</li>
    <li><strong>Review obsolescence</strong> — Check the Drives and Power Plants tabs for dominated items</li>
    <li><strong>Explore combinations</strong> — View valid drive+reactor pairs and their performance</li>
    <li><strong>Design missions</strong> — Use the mission search to find configurations meeting your Δv/accel targets</li>
  </ol>

  <h2>Data Sources</h2>
  <p>The app reads game data from JSON templates in your Terra Invicta installation:</p>
  <ul>
    <li><code>TIDriveTemplate.json</code> — drive specifications</li>
    <li><code>TIPowerPlantTemplate.json</code> — reactor specifications</li>
  </ul>
  <p>Search locations (in order):</p>
  <ol>
    <li>Environment variable: <code>TI_TEMPLATES_DIR</code></li>
        <li>Default Steam path (Windows): <code>C:\\Program Files (x86)\\Steam\\steamapps\\common\\Terra Invicta\\TerraInvicta_Data\\StreamingAssets\\Templates</code></li>
    <li>Current working directory (for manual copies)</li>
  </ol>
  <div class="tip">
    <strong>Tip:</strong> If templates aren't found, set the <code>TI_TEMPLATES_DIR</code> environment variable 
    to point to your game's Templates folder.
  </div>

  <h2>Profiles</h2>
  <p>Save and restore your configuration as JSON files:</p>
  <ul>
    <li><strong>Download profile JSON</strong> — Export current settings (unlocked items, resources, weights, reference masses)</li>
    <li><strong>Upload profile JSON</strong> — Restore a previously saved configuration</li>
  </ul>
  <p>Profiles work both locally and on Streamlit Cloud with no server-side storage required.</p>

  <h2>Global Settings</h2>
  
  <h3>Resource Abundance</h3>
  <p>Mark which resources are abundant in your campaign. Drives using non-abundant resources are flagged 
  as using <strong>scarce propellant</strong>, which prevents them from dominating drives with abundant-only fuel.</p>
  <p>Resources: Water, Volatiles, Base Metals, Noble Metals, Fissiles, Antimatter, Exotics</p>

  <h3>Obsolescence Options</h3>
  <ul>
    <li><strong>Care about backup power</strong> — Drives providing idle backup power (Always/DriveIdle modes) 
    cannot be dominated by drives without this feature</li>
    <li><strong>Care about crew size</strong> — Reactors with lower crew requirements are preferred; 
    high-crew reactors cannot dominate low-crew ones</li>
    <li><strong>Don't mark drives obsolete within same family</strong> — Prevents intra-family dominance 
    (e.g., Resistojet x2 won't mark x1 obsolete)</li>
  </ul>

  <h3>Fuel Cost Weights</h3>
  <p>Assign weights to each resource type to calculate an <strong>Expensive Fuel Score</strong> for each drive. 
  Drives using high-weight resources receive higher scores. This metric appears in tables and affects combo-level dominance.</p>

  <h3>Reference Ship</h3>
  <p>Set reference payload and propellant masses (up to 300,000 tons each). The app calculates these metrics for each valid combo:</p>
  <ul>
    <li>Ref Delta-v (km/s)</li>
    <li>Ref Cruise Acceleration (g or milli-g)</li>
    <li>Ref Combat Acceleration (g or milli-g)</li>
    <li>Total Wet Mass (tons)</li>
    <li>Power Ratio (reactor output / drive requirement)</li>
  </ul>

  <h3>Display Options</h3>
  <p><strong>Display accelerations in milligees</strong> — Toggle between g and milli-g units for acceleration display 
  (calculations remain in g internally)</p>

  <h2>Unlocking Content</h2>
  
  <h3>Drives</h3>
  <p>Drives unlock by <strong>family</strong> (e.g., "Tungsten Resistojet"), automatically including all x1–x6 variants.</p>
  <p>Controls: Search, Add Family, Unlock ALL, Clear All, Remove Selected</p>

  <h3>Power Plants</h3>
  <p>Reactors unlock individually by exact name (no family grouping).</p>
  <p>Controls: Search, Add Reactor, Unlock ALL, Clear All, Remove Selected</p>

  <h2>Obsolescence Analysis</h2>
  
  <h3>Drive Obsolescence (🚀 Drives Tab)</h3>
  <p>Drives are marked <strong>Obsolete</strong> when dominated on all of:</p>
  <ul>
    <li>Thrust (higher is better)</li>
    <li>Exhaust Velocity (higher is better)</li>
    <li>Power Use Efficiency (higher is better)</li>
    <li>Drive Mass (lower is better)</li>
    <li>Fuel scarcity (non-scarce preferred)</li>
    <li>Backup power (if enabled; backup preferred)</li>
  </ul>
    <p>The <strong>Dominates (count)</strong> column shows how many other drives each drive dominates. 
    Use checkboxes on the left to show/hide columns.</p>
    <p><strong>Domination Efficiency</strong> = (Dominates count × 1000) / Unlock Total Research Cost — higher is better.</p>

  <h3>Reactor Obsolescence (⚡ Power Plants Tab)</h3>
  <p>Reactors are marked obsolete when dominated on all of:</p>
  <ul>
    <li>Max Output (GW) — higher is better</li>
    <li>Efficiency — higher is better</li>
    <li>General Use flag — True is better</li>
    <li>Specific Power (tons/GW) — lower is better</li>
    <li>Crew size — lower is better (if enabled)</li>
  </ul>
    <p>The <strong>Dominates (count)</strong> column shows domination count. Column visibility is customizable.</p>
    <p><strong>Domination Efficiency</strong> = (Dominates count × 1000) / Unlock Total Research Cost — higher is better.</p>

  <h2>Valid Combinations</h2>
  <p>Below the tabs, view all valid (drive, reactor) pairs where:</p>
  <ul>
    <li>Both drive and reactor are non-obsolete</li>
    <li>Reactor class matches drive requirements</li>
    <li>Reactor provides sufficient power for the drive</li>
  </ul>
  <p>Each combo shows reference metrics (Δv, accel, power ratio, mass, fuel score). 
  Enable <strong>Hide dominated combos</strong> to filter combo-level obsolete pairs.</p>
  <p>Reactor mass is automatically scaled to match the drive's power requirement.</p>

  <h2>Scatterplot Visualization</h2>
  <p>Plot any two metrics against each other:</p>
  <ul>
    <li>Drive Expensive Fuel Score</li>
    <li>Ref Delta-v (km/s)</li>
    <li>Ref Cruise Accel</li>
    <li>Ref Combat Accel</li>
    <li>Power Ratio (PP/Drive)</li>
    <li>Total Wet Mass (tons)</li>
  </ul>
  <p><strong>Default:</strong> Ref Cruise Accel (X) vs Ref Delta-v (Y)</p>
  <div class="tip">
    <strong>Tip:</strong> If you select the same metric for both axes, the app displays 
    an informational message instead of a broken chart.
  </div>

  <h2>Mission Feasibility Search</h2>
  <p>Find configurations that meet specific mission requirements:</p>
  <ol>
    <li>Set <strong>Target Δv</strong> (km/s)</li>
    <li>Choose <strong>Acceleration type</strong> (cruise or combat)</li>
    <li>Set <strong>Target Acceleration</strong> (g or milli-g)</li>
    <li>Set <strong>Minimum Payload Mass</strong> (tons, up to 300,000)</li>
  </ol>
  <p>The app searches payload and propellant mass combinations for each valid combo, showing:</p>
  <ul>
    <li>Payload Mass (tons)</li>
    <li>Propellant Mass (tons)</li>
    <li>Result Delta-v (km/s)</li>
    <li>Result Acceleration (g or milli-g)</li>
    <li>Additional Possible Payload (tons) — how much more payload can be added beyond the minimum</li>
  </ul>

  <h2>Tips &amp; Best Practices</h2>
  <ul>
    <li><strong>Start small:</strong> Unlock a few drives/reactors to understand dominance before unlocking everything</li>
    <li><strong>Adjust weights:</strong> Fine-tune fuel cost weights based on your campaign's resource constraints</li>
    <li><strong>Use profiles:</strong> Save configurations for different campaign stages or scenarios</li>
    <li><strong>Check dominance counts:</strong> High domination counts indicate generally superior drives/reactors</li>
    <li><strong>Mission search limitations:</strong> Results are approximate; verify in-game for critical missions</li>
  </ul>

  <hr style="margin-top: 3rem; border: none; border-top: 1px solid #ddd;" />
  <p style="font-size: 0.9em; color: #777; text-align: center;">
    Not affiliated with Hooded Horse, Pavonis Interactive, or the Terra Invicta team.<br />
    Fan-made analysis tool using exported game data.
  </p>
</body>
</html>

"""

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

DEFAULT_REF_PAYLOAD_TONS = 1000.0
DEFAULT_REF_PROPELLANT_TONS = 1000.0

DEFAULT_TECH_MAX_STEPS = 3
DEFAULT_TECH_TOP_N = 15
DEFAULT_TECH_HIDE_ZERO = True
MAX_TECH_MAX_STEPS = 10
MAX_TECH_TOP_N = 200

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
            - prereqs: list of prerequisite project dataNames (AND)
            - alt_prereqs: list of alternative prerequisites (see below)

        Terra Invicta project templates sometimes include fields like altPrereq0,
        altPrereq1, ... which represent alternative ways to satisfy (typically) the
        *first* prerequisite in the prereqs list. In those cases, the unlock rule is:

            - all prereqs[1:] must be satisfied, AND
            - at least one of {prereqs[0]} ∪ alt_prereqs must be satisfied
    """
    graph: Dict[str, Dict[str, Any]] = {}

    for _, row in project_df.iterrows():
        pid = str(row.get("dataName", "")).strip()
        if not pid:
            continue

        cost = float(row.get("researchCost", 0.0))

        prereqs: List[str] = []
        alt_prereqs: List[str] = []

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
                    alt_prereqs.append(s)

        prereqs = list({p for p in prereqs if p})
        alt_prereqs = list({p for p in alt_prereqs if p})

        graph[pid] = {
            "cost": cost,
            "prereqs": prereqs,
            "alt_prereqs": alt_prereqs,
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

        prereqs = list(node.get("prereqs", []) or [])
        alt_prereqs = list(node.get("alt_prereqs", []) or [])

        # Base case: no prerequisites
        if not prereqs and not alt_prereqs:
            memo[pid] = total
            return total

        # If there are alternative prerequisites, treat them as alternatives to
        # satisfying the first prereq.
        if alt_prereqs:
            fixed = prereqs[1:] if prereqs else []
            options = []
            if prereqs:
                options.append(prereqs[0])
            options.extend(alt_prereqs)

            for pre in fixed:
                total += dfs(pre, new_visiting)

            if options:
                total += min(dfs(opt, new_visiting) for opt in options)
        else:
            for pre in prereqs:
                total += dfs(pre, new_visiting)

        memo[pid] = total
        return total

    for pid in project_graph.keys():
        dfs(pid, set())

    return memo


def infer_completed_projects_from_unlocks(
    drive_df: pd.DataFrame,
    pp_df: pd.DataFrame,
    unlocked_drive_families: List[str],
    unlocked_pp_names: List[str],
) -> set:
    projects: set = set()

    if not drive_df.empty:
        fam_set = set(unlocked_drive_families)
        for _, row in drive_df.iterrows():
            if row.get("FamilyName") in fam_set:
                proj = str(row.get("requiredProjectName", "")).strip()
                if proj:
                    projects.add(proj)

    if not pp_df.empty:
        pp_set = set(unlocked_pp_names)
        for _, row in pp_df.iterrows():
            if row.get("DisplayName") in pp_set:
                proj = str(row.get("requiredProjectName", "")).strip()
                if proj:
                    projects.add(proj)

    return projects


def compute_reachable_projects(
    project_graph: Dict[str, Dict[str, Any]],
    completed_projects: set,
    max_steps: int,
) -> set:
    reachable = set(completed_projects)
    steps = max(0, int(max_steps))

    def prereq_satisfied(pr: str) -> bool:
        # Some prerequisites in TIProjectTemplate are *global tech* IDs (e.g. "ArcLasers")
        # rather than projects listed in TIProjectTemplate. Since this app doesn't track
        # global tech unlocks, treat non-project prerequisites as already satisfied so
        # reachability isn't artificially blocked.
        return (pr in reachable) or (pr not in project_graph)

    for _ in range(steps):
        newly: set = set()
        for pid, node in project_graph.items():
            if pid in reachable:
                continue
            prereqs = list(node.get("prereqs", []) or [])
            alt_prereqs = list(node.get("alt_prereqs", []) or [])

            if not prereqs and not alt_prereqs:
                newly.add(pid)
                continue

            if alt_prereqs:
                fixed = prereqs[1:] if prereqs else []
                options = []
                if prereqs:
                    options.append(prereqs[0])
                options.extend(alt_prereqs)

                if all(prereq_satisfied(pre) for pre in fixed) and any(
                    prereq_satisfied(opt) for opt in options
                ):
                    newly.add(pid)
            else:
                if all(prereq_satisfied(pre) for pre in prereqs):
                    newly.add(pid)

        if not newly:
            break
        reachable.update(newly)

    return reachable


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
    st.session_state["tech_max_steps"] = int(profile.get("tech_max_steps", DEFAULT_TECH_MAX_STEPS))
    st.session_state["tech_top_n"] = int(profile.get("tech_top_n", DEFAULT_TECH_TOP_N))
    st.session_state["tech_hide_zero"] = bool(profile.get("tech_hide_zero", DEFAULT_TECH_HIDE_ZERO))

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
        "tech_max_steps": int(st.session_state.get("tech_max_steps", DEFAULT_TECH_MAX_STEPS)),
        "tech_top_n": int(st.session_state.get("tech_top_n", DEFAULT_TECH_TOP_N)),
        "tech_hide_zero": bool(st.session_state.get("tech_hide_zero", DEFAULT_TECH_HIDE_ZERO)),
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

    def to_int(v, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default

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
    tech_max_steps = clamp(
        float(to_int(raw_profile.get("tech_max_steps", DEFAULT_TECH_MAX_STEPS), DEFAULT_TECH_MAX_STEPS)),
        0,
        MAX_TECH_MAX_STEPS,
    )
    tech_top_n = clamp(
        float(to_int(raw_profile.get("tech_top_n", DEFAULT_TECH_TOP_N), DEFAULT_TECH_TOP_N)),
        1,
        MAX_TECH_TOP_N,
    )
    tech_hide_zero = to_bool(raw_profile.get("tech_hide_zero", DEFAULT_TECH_HIDE_ZERO), DEFAULT_TECH_HIDE_ZERO)

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
        "tech_max_steps": int(tech_max_steps),
        "tech_top_n": int(tech_top_n),
        "tech_hide_zero": tech_hide_zero,
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

    # Domination Efficiency = (Dominates (count) * 1000) / Unlock Total Research Cost (higher is better)
    if "Unlock Total Research Cost" in feat_df.columns:
        unlock_costs = feat_df["Unlock Total Research Cost"].tolist()
        dom_eff: List[Optional[float]] = []
        for idx in range(n):
            count = dominates_count[idx]
            cost = unlock_costs[idx] if idx < len(unlock_costs) else 0.0
            if count > 0 and cost not in (None, 0, 0.0):
                dom_eff.append((float(count) * 1000.0) / float(cost))
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

    # Domination Efficiency = (Dominates (count) * 1000) / Unlock Total Research Cost (higher is better)
    if "Unlock Total Research Cost" in feat_df.columns:
        unlock_costs = feat_df["Unlock Total Research Cost"].tolist()
        dom_eff: List[Optional[float]] = []
        for idx in range(n):
            count = dominates_count[idx]
            cost = unlock_costs[idx] if idx < len(unlock_costs) else 0.0
            if count > 0 and cost not in (None, 0, 0.0):
                dom_eff.append((float(count) * 1000.0) / float(cost))
            else:
                dom_eff.append(None)
        out["Domination Efficiency"] = dom_eff

    return out


def _annotate_drive_suggestion_dominance(
    candidates_df: pd.DataFrame,
    unlocked_df: pd.DataFrame,
    care_backup: bool,
    ignore_intraclass: bool,
    class_col: str = "FamilyName",
) -> pd.DataFrame:
    """Annotate candidate drives with both raw and *new* dominance metrics.

    New dominance metrics discount targets that are already dominated at least once
    by currently unlocked drives.
    """
    if candidates_df is None or candidates_df.empty:
        return pd.DataFrame()

    n = len(candidates_df)
    obsolete_flags: List[bool] = [False] * n
    dominated_by: List[List[str]] = [[] for _ in range(n)]
    dominates_count: List[int] = [0] * n

    # Targets (by candidate index) that are already dominated by any unlocked drive.
    already_dominated_target: List[bool] = [False] * n
    if unlocked_df is not None and not unlocked_df.empty:
        for i in range(n):
            row_b = candidates_df.iloc[i]
            for _, row_a in unlocked_df.iterrows():
                if dominates_drive(row_a, row_b, care_backup, ignore_intraclass, class_col):
                    already_dominated_target[i] = True
                    break

    # Track which targets each candidate dominates (as indices).
    dominated_targets_by: List[set] = [set() for _ in range(n)]
    new_dominated_targets_by: List[set] = [set() for _ in range(n)]

    for i in range(n):
        row_b = candidates_df.iloc[i]
        for j in range(n):
            if i == j:
                continue
            row_a = candidates_df.iloc[j]
            if dominates_drive(row_a, row_b, care_backup, ignore_intraclass, class_col):
                # row_a dominates row_b
                obsolete_flags[i] = True
                dominated_by[i].append(row_a["Name"])
                dominates_count[j] += 1
                dominated_targets_by[j].add(i)
                if not already_dominated_target[i]:
                    new_dominated_targets_by[j].add(i)

    out = candidates_df.copy()
    out["Obsolete"] = obsolete_flags
    out["Dominates (count)"] = dominates_count
    out["Dominated By"] = [", ".join(lst) if lst else "" for lst in dominated_by]

    new_dominances = [len(s) for s in new_dominated_targets_by]
    out["New Dominances"] = new_dominances

    if "Unlock Total Research Cost" in out.columns:
        unlock_costs = out["Unlock Total Research Cost"].tolist()
        dom_eff: List[Optional[float]] = []
        new_dom_eff: List[Optional[float]] = []
        for idx in range(n):
            cost = unlock_costs[idx] if idx < len(unlock_costs) else 0.0
            count = dominates_count[idx]
            new_count = new_dominances[idx]

            if count > 0 and cost not in (None, 0, 0.0):
                dom_eff.append((float(count) * 1000.0) / float(cost))
            else:
                dom_eff.append(None)

            if new_count > 0 and cost not in (None, 0, 0.0):
                new_dom_eff.append((float(new_count) * 1000.0) / float(cost))
            else:
                new_dom_eff.append(None)

        out["Domination Efficiency"] = dom_eff
        out["New Domination Efficiency"] = new_dom_eff

    return out


def _annotate_pp_suggestion_dominance(
    candidates_df: pd.DataFrame,
    unlocked_df: pd.DataFrame,
    care_crew: bool,
) -> pd.DataFrame:
    """Annotate candidate reactors with both raw and *new* dominance metrics.

    New dominance metrics discount targets that are already dominated at least once
    by currently unlocked reactors.
    """
    if candidates_df is None or candidates_df.empty:
        return pd.DataFrame()

    n = len(candidates_df)
    obsolete_flags: List[bool] = [False] * n
    dominated_by: List[List[str]] = [[] for _ in range(n)]
    dominates_count: List[int] = [0] * n

    already_dominated_target: List[bool] = [False] * n
    if unlocked_df is not None and not unlocked_df.empty:
        for i in range(n):
            row_b = candidates_df.iloc[i]
            for _, row_a in unlocked_df.iterrows():
                if dominates_pp(row_a, row_b, care_crew):
                    already_dominated_target[i] = True
                    break

    new_dominated_targets_by: List[set] = [set() for _ in range(n)]

    for i in range(n):
        row_b = candidates_df.iloc[i]
        for j in range(n):
            if i == j:
                continue
            row_a = candidates_df.iloc[j]
            if dominates_pp(row_a, row_b, care_crew):
                obsolete_flags[i] = True
                dominated_by[i].append(row_a["Name"])
                dominates_count[j] += 1
                if not already_dominated_target[i]:
                    new_dominated_targets_by[j].add(i)

    out = candidates_df.copy()
    out["Obsolete"] = obsolete_flags
    out["Dominates (count)"] = dominates_count
    out["Dominated By"] = [", ".join(lst) if lst else "" for lst in dominated_by]

    new_dominances = [len(s) for s in new_dominated_targets_by]
    out["New Dominances"] = new_dominances

    if "Unlock Total Research Cost" in out.columns:
        unlock_costs = out["Unlock Total Research Cost"].tolist()
        dom_eff: List[Optional[float]] = []
        new_dom_eff: List[Optional[float]] = []
        for idx in range(n):
            cost = unlock_costs[idx] if idx < len(unlock_costs) else 0.0
            count = dominates_count[idx]
            new_count = new_dominances[idx]

            if count > 0 and cost not in (None, 0, 0.0):
                dom_eff.append((float(count) * 1000.0) / float(cost))
            else:
                dom_eff.append(None)

            if new_count > 0 and cost not in (None, 0, 0.0):
                new_dom_eff.append((float(new_count) * 1000.0) / float(cost))
            else:
                new_dom_eff.append(None)

        out["Domination Efficiency"] = dom_eff
        out["New Domination Efficiency"] = new_dom_eff

    return out


def _sort_suggestions(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    dom_eff_col = "New Domination Efficiency" if "New Domination Efficiency" in out.columns else "Domination Efficiency"
    dom_count_col = "New Dominances" if "New Dominances" in out.columns else "Dominates (count)"

    out["__dom_eff_sort"] = (
        out[dom_eff_col].fillna(-math.inf)
        if dom_eff_col in out.columns
        else -math.inf
    )
    out["__dom_count_sort"] = (
        out[dom_count_col].fillna(0)
        if dom_count_col in out.columns
        else 0
    )
    out["__unlock_cost_sort"] = (
        out["Unlock Total Research Cost"].replace({None: math.inf}).fillna(math.inf)
        if "Unlock Total Research Cost" in out.columns
        else math.inf
    )

    out = out.sort_values(
        ["__dom_eff_sort", "__dom_count_sort", "__unlock_cost_sort"],
        ascending=[False, False, True],
    )

    return out.drop(columns=["__dom_eff_sort", "__dom_count_sort", "__unlock_cost_sort"], errors="ignore")


def compute_drive_tech_suggestions(
    drive_feat_all: pd.DataFrame,
    unlocked_drive_families: List[str],
    reachable_projects: set,
    care_backup: bool,
    ignore_intraclass: bool,
    hide_zero: bool,
    top_n: int,
) -> pd.DataFrame:
    if drive_feat_all is None or drive_feat_all.empty:
        return pd.DataFrame()

    proj_series = drive_feat_all["Unlock Project"].fillna("").astype(str)
    reachable_mask = proj_series.eq("") | proj_series.isin(reachable_projects)
    unlocked_mask = drive_feat_all["FamilyName"].isin(unlocked_drive_families)

    candidates = drive_feat_all[reachable_mask & ~unlocked_mask].copy()
    if candidates.empty:
        return pd.DataFrame()

    unlocked_df = drive_feat_all[unlocked_mask].copy()
    annotated = _annotate_drive_suggestion_dominance(
        candidates,
        unlocked_df,
        care_backup=care_backup,
        ignore_intraclass=ignore_intraclass,
        class_col="FamilyName",
    )

    if hide_zero:
        if "New Dominances" in annotated.columns:
            annotated = annotated[annotated["New Dominances"] > 0]
        elif "Dominates (count)" in annotated.columns:
            annotated = annotated[annotated["Dominates (count)"] > 0]

    if "Unlock Total Research Cost" in annotated.columns:
        annotated = annotated[annotated["Unlock Total Research Cost"] > 0]

    top_n = max(1, int(top_n))

    return _sort_suggestions(annotated).head(top_n)


def compute_pp_tech_suggestions(
    pp_feat_all: pd.DataFrame,
    unlocked_pp_names: List[str],
    reachable_projects: set,
    care_crew: bool,
    hide_zero: bool,
    top_n: int,
) -> pd.DataFrame:
    if pp_feat_all is None or pp_feat_all.empty:
        return pd.DataFrame()

    proj_series = pp_feat_all["Unlock Project"].fillna("").astype(str)
    reachable_mask = proj_series.eq("") | proj_series.isin(reachable_projects)
    unlocked_mask = pp_feat_all["Name"].isin(unlocked_pp_names)

    candidates = pp_feat_all[reachable_mask & ~unlocked_mask].copy()
    if candidates.empty:
        return pd.DataFrame()

    unlocked_df = pp_feat_all[unlocked_mask].copy()
    annotated = _annotate_pp_suggestion_dominance(
        candidates,
        unlocked_df,
        care_crew=care_crew,
    )

    if hide_zero:
        if "New Dominances" in annotated.columns:
            annotated = annotated[annotated["New Dominances"] > 0]
        elif "Dominates (count)" in annotated.columns:
            annotated = annotated[annotated["Dominates (count)"] > 0]

    if "Unlock Total Research Cost" in annotated.columns:
        annotated = annotated[annotated["Unlock Total Research Cost"] > 0]

    top_n = max(1, int(top_n))

    return _sort_suggestions(annotated).head(top_n)


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

        # Analytic solution (no grid search)
        try:
            mass_ratio = math.exp(dv_target_kps / ev_kps)
        except OverflowError:
            mass_ratio = float("inf")

        if not math.isfinite(mass_ratio) or mass_ratio <= 1.0:
            continue

        # Accel constraint: m_wet = (m0 + Mp) * mass_ratio <= thrust / (a*g)
        m_wet_max_accel = t_eff / (accel_target_g * 1000.0 * g_m_s2)
        if m_wet_max_accel <= 0.0:
            continue
        mp_max_accel = m_wet_max_accel / mass_ratio - m0

        # Propellant upper bound constraint: prop_needed = (m0 + Mp) * (mass_ratio - 1) <= prop_max
        mp_max_prop = prop_max / (mass_ratio - 1.0) - m0 if prop_max > 0 else mp_max_accel

        # Overall max payload allowed by accel and prop bounds
        mp_max_feasible = min(mp_max_accel, mp_max_prop)
        if mp_max_feasible < payload_min:
            continue

        # Use requested minimum payload if feasible; otherwise cap at mp_max_feasible
        payload_sol = payload_min

        # Compute required propellant for this payload
        prop_sol = (m0 + payload_sol) * (mass_ratio - 1.0)

        # Enforce propellant bounds
        if prop_sol < prop_min or prop_sol > prop_max:
            continue

        # Compute actual wet mass, accel, dv
        m_wet = m0 + payload_sol + prop_sol
        accel_sol = t_eff / (m_wet * 1000.0 * g_m_s2)
        if accel_sol < accel_target_g:
            continue
        dv_sol = dv_target_kps  # by construction

        # Additional payload possible beyond what we're already carrying
        additional_payload = mp_max_feasible - payload_sol
        if additional_payload < 0.0:
            additional_payload = 0.0

        results.append(
            {
                "Drive": row["Drive"],
                "Power Plant": row["Power Plant"],
                "Payload Mass (tons)": payload_sol,
                "Propellant Mass (tons)": prop_sol,
                "Result Delta-v (km/s)": dv_sol,
                "Result Accel (g)": accel_sol,
                "Additional Possible Payload (tons)": additional_payload,
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

    if "tech_max_steps" not in st.session_state:
        st.session_state["tech_max_steps"] = DEFAULT_TECH_MAX_STEPS
    if "tech_top_n" not in st.session_state:
        st.session_state["tech_top_n"] = DEFAULT_TECH_TOP_N
    if "tech_hide_zero" not in st.session_state:
        st.session_state["tech_hide_zero"] = DEFAULT_TECH_HIDE_ZERO

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
                        "tech_max_steps": MAX_TECH_MAX_STEPS,
                        "tech_top_n": MAX_TECH_TOP_N,
                        "tech_hide_zero": True,
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
    drive_feat_all = build_drive_features(
        drive_raw,
        resource_abundance,
        backup_col=backup_col,
        req_pp_col=req_pp_col,
        fuel_weights=fuel_weights,
        project_total_costs=project_total_costs,
    )

    unlocked_drive_families = st.session_state.unlocked_drive_families
    if drive_feat_all.empty or not unlocked_drive_families:
        drive_feat = None
    else:
        drive_feat = annotate_drive_obsolescence(
            drive_feat_all[drive_feat_all["FamilyName"].isin(unlocked_drive_families)],
            care_backup,
            ignore_intraclass,
            class_col="FamilyName",
        )

    pp_feat_all = build_pp_features(pp_raw, project_total_costs=project_total_costs)

    unlocked_pp_names = st.session_state.unlocked_pp
    if pp_feat_all.empty or not unlocked_pp_names:
        pp_feat = None
    else:
        pp_feat = annotate_pp_obsolescence(
            pp_feat_all[pp_feat_all["Name"].isin(unlocked_pp_names)], care_crew=care_crew
        )

    # -----------------------------------------------------------------------
    # Tech path suggestions (shared controls)
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Tech path suggestions")

    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        st.number_input(
            "Max project unlock steps from current tech",
            min_value=0,
            max_value=MAX_TECH_MAX_STEPS,
            step=1,
            value=int(st.session_state.get("tech_max_steps", DEFAULT_TECH_MAX_STEPS)),
            key="tech_max_steps",
        )
    with col_t2:
        st.number_input(
            "Show top N suggestions",
            min_value=1,
            max_value=MAX_TECH_TOP_N,
            step=1,
            value=int(st.session_state.get("tech_top_n", DEFAULT_TECH_TOP_N)),
            key="tech_top_n",
        )
    with col_t3:
        st.checkbox(
            "Hide suggestions with zero domination",
            value=bool(st.session_state.get("tech_hide_zero", DEFAULT_TECH_HIDE_ZERO)),
            key="tech_hide_zero",
        )

    tech_max_steps = int(st.session_state.get("tech_max_steps", DEFAULT_TECH_MAX_STEPS))
    tech_top_n = int(st.session_state.get("tech_top_n", DEFAULT_TECH_TOP_N))
    tech_hide_zero = bool(st.session_state.get("tech_hide_zero", DEFAULT_TECH_HIDE_ZERO))

    completed_projects = infer_completed_projects_from_unlocks(
        drive_raw,
        pp_raw,
        unlocked_drive_families,
        unlocked_pp_names,
    )
    reachable_projects = compute_reachable_projects(
        project_graph,
        completed_projects,
        tech_max_steps,
    )

    drive_suggestions = compute_drive_tech_suggestions(
        drive_feat_all,
        unlocked_drive_families,
        reachable_projects,
        care_backup,
        ignore_intraclass,
        tech_hide_zero,
        tech_top_n,
    )

    pp_suggestions = compute_pp_tech_suggestions(
        pp_feat_all,
        unlocked_pp_names,
        reachable_projects,
        care_crew,
        tech_hide_zero,
        tech_top_n,
    )

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

        st.markdown("#### Tech path suggestions (drives)")
        if drive_suggestions is None or drive_suggestions.empty:
            st.info(
                "No reachable drives within the selected step limit improve dominance metrics."
            )
        else:
            drive_suggestion_cols = [
                c
                for c in [
                    "Name",
                    "FamilyName",
                    "New Domination Efficiency",
                    "New Dominances",
                    "Domination Efficiency",
                    "Dominates (count)",
                    "Unlock Project",
                    "Unlock Total Research Cost",
                ]
                if c in drive_suggestions.columns
            ]
            st.dataframe(
                drive_suggestions.loc[:, drive_suggestion_cols],
                use_container_width=True,
                key="df_drive_tech_suggestions",
            )

        if drive_feat is not None:
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
                st.caption(
                    "Domination Efficiency = (Dominates count × 1000) / Unlock Total Research Cost — higher is better."
                )
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

        st.markdown("#### Tech path suggestions (power plants)")
        if pp_suggestions is None or pp_suggestions.empty:
            st.info(
                "No reachable reactors within the selected step limit improve dominance metrics."
            )
        else:
            pp_suggestion_cols = [
                c
                for c in [
                    "Name",
                    "Class",
                    "New Domination Efficiency",
                    "New Dominances",
                    "Domination Efficiency",
                    "Dominates (count)",
                    "Unlock Project",
                    "Unlock Total Research Cost",
                ]
                if c in pp_suggestions.columns
            ]
            st.dataframe(
                pp_suggestions.loc[:, pp_suggestion_cols],
                use_container_width=True,
                key="df_pp_tech_suggestions",
            )

        if pp_feat is not None:
            base_cols = ["Name", "Obsolete", "Dominates (count)", "Dominated By"]
            pp_property_cols = [c for c in pp_feat.columns if c not in base_cols]

            if "pp_visible_props" not in st.session_state:
                st.session_state.pp_visible_props = {
                    c: True for c in pp_property_cols
                }

            left_col, right_col = st.columns([1, 4])

            with left_col:
                st.markdown("**Reactor columns**")
                st.caption(
                    "Domination Efficiency = (Dominates count × 1000) / Unlock Total Research Cost — higher is better."
                )
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
