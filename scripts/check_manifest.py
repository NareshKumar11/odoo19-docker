import ast
import os
import sys

addons_path = "addons"

errors = []

if not os.path.exists(addons_path):
    print("No addons directory found.")
    sys.exit(0)

for module in os.listdir(addons_path):
    manifest = os.path.join(addons_path, module, "__manifest__.py")

    if os.path.isfile(manifest):
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                ast.literal_eval(f.read())
            print(f"✓ {module}")
        except Exception as e:
            errors.append(f"{module}: {e}")

if errors:
    print("\nManifest Errors:")
    for err in errors:
        print(err)
    sys.exit(1)

print("\nAll manifests are valid.")
