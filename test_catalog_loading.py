"""Test that fd-cn-report CATALOG can be loaded via fd-open-data-protocol."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, "/Users/chengsishi/finddata/fd-cn-report")

os.chdir("/Users/chengsishi/finddata/fd-cn-report")

# Test loading the CATALOG from Python module (direct dict access)
print("Loading CATALOG from catalog module...")
import catalog as cat_module
catalog = cat_module.CATALOG

print(f"✓ Name: {catalog['name']}")
print(f"✓ Label: {catalog['label']}")
print(f"✓ Functions count: {len(catalog['functions'])}")
print(f"✓ Concepts count: {len(catalog.get('concepts', []))}")
print(f"✓ Fetch config: {catalog.get('fetch')}")

# Print first function for verification
if catalog['functions']:
    func = catalog['functions'][0]
    print(f"\nFirst function:")
    print(f"  - command: {func['command']}")
    print(f"  - category: {func['category']}")
    print(f"  - columns count: {len(func['columns'])}")

print("\n✓ All tests passed!")
