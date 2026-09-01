"""
Fleet Management Commands for devctl.
Handles node registration, pruning, and fleet-wide operations.
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List


def normalize_node_name(name: str) -> str:
    """Normalize node names to prevent duplicates (vm4 vs vm-04)."""
    if not name:
        return name
    # Remove common prefixes/suffixes
    name = name.strip().lower()
    # Normalize vm-XX to vmXX format
    if name.startswith("vm-") and name[3:].isdigit():
        return f"vm{name[3:]}"
    return name


def cmd_fleet_prune(args):
    """Remove stale nodes that haven't sent heartbeats recently."""
    from devctl.core.fleet_state import FleetState

    state = FleetState()
    nodes = state.get_all_nodes()

    if not nodes:
        print("[✓] No nodes in fleet.")
        return

    # Default: prune nodes older than 1 hour
    max_age_seconds = args.max_age * 60 if hasattr(args, "max_age") and args.max_age else 3600
    current_time = time.time()

    stale_nodes = []
    active_nodes = []

    for node_name, node_data in nodes.items():
        last_seen = node_data.get("last_seen", 0)
        age_seconds = current_time - last_seen

        if age_seconds > max_age_seconds:
            stale_nodes.append((node_name, age_seconds))
        else:
            active_nodes.append(node_name)

    print(f"\n{'═' * 70}")
    print(f"🗑️  FLEET PRUNE")
    print(f"{'═' * 70}")
    print(f"• Total nodes:    {len(nodes)}")
    print(f"• Active nodes:   {len(active_nodes)}")
    print(f"• Stale nodes:    {len(stale_nodes)}")
    print(f"• Max age:        {max_age_seconds // 60} minutes")
    print()

    if not stale_nodes:
        print("[✓] No stale nodes to prune.")
        return

    print("Stale nodes to remove:")
    for node_name, age_seconds in stale_nodes:
        age_min = age_seconds / 60
        print(f"  • {node_name} (last seen {age_min:.0f}m ago)")

    if not args.yes:
        print(f"\n[?] Remove {len(stale_nodes)} stale node(s)?")
        confirm = input("    Type 'yes' to proceed: ").strip().lower()
        if confirm != "yes":
            print("[✗] Prune cancelled.")
            return

    # Remove stale nodes
    removed = 0
    for node_name, _ in stale_nodes:
        try:
            state.remove_node(node_name)
            removed += 1
            print(f"  [✓] Removed: {node_name}")
        except Exception as e:
            print(f"  [✗] Failed to remove {node_name}: {e}")

    print(f"\n[✓] Pruned {removed} stale node(s).")


def cmd_fleet_list(args):
    """List all nodes in the fleet with their status."""
    from devctl.core.fleet_state import FleetState

    state = FleetState()
    nodes = state.get_all_nodes()

    if not nodes:
        print("[✓] No nodes in fleet.")
        return

    current_time = time.time()

    print(f"\n{'═' * 70}")
    print(f"📡 FLEET NODES")
    print(f"{'═' * 70}")
    print(f"{'NODE':<20} {'STATUS':<12} {'LAST SEEN':<15} {'CONTAINERS':<12} {'SERVICES':<10}")
    print(f"{'─' * 70}")

    for node_name in sorted(nodes.keys()):
        node_data = nodes[node_name]
        last_seen = node_data.get("last_seen", 0)
        age_seconds = current_time - last_seen

        # Determine status
        if age_seconds < 60:
            status = "🟢 ONLINE"
        elif age_seconds < 300:
            status = "🟡 STALE"
        else:
            status = "🔴 OFFLINE"

        containers = node_data.get("containers_count", 0)
        services = len(node_data.get("services", []))

        # Format last seen
        if age_seconds < 60:
            last_seen_str = f"{int(age_seconds)}s ago"
        elif age_seconds < 3600:
            last_seen_str = f"{int(age_seconds / 60)}m ago"
        else:
            last_seen_str = f"{int(age_seconds / 3600)}h ago"

        print(f"{node_name:<20} {status:<12} {last_seen_str:<15} {containers:<12} {services:<10}")

    print()
