import ast
import os
import sys

ADDONS_PATH = "custom_addons"
errors = []

if not os.path.isdir(ADDONS_PATH):
    print(f"'{ADDONS_PATH}' directory not found.")
    sys.exit(1)

modules_checked = 0

for module in sorted(os.listdir(ADDONS_PATH)):
    module_path = os.path.join(ADDONS_PATH, module)

    if not os.path.isdir(module_path):
        continue

    manifest_path = os.path.join(module_path, "__manifest__.py")

    if os.path.isfile(manifest_path):
        modules_checked += 1
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                ast.literal_eval(f.read())
            print(f"✓ {module}")
        except Exception as e:
            errors.append(f"{module}: {e}")
    else:
        print(f"⚠ {module} - __manifest__.py not found")

print(f"\nChecked {modules_checked} module(s).")

if errors:
    print("\nManifest Errors:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("\n✅ All manifest files are valid.")
