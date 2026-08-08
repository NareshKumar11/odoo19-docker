import os
import sys
import xml.etree.ElementTree as ET

ADDONS_PATH = "custom_addons"
errors = []

if not os.path.isdir(ADDONS_PATH):
    print(f"❌ Directory not found: {ADDONS_PATH}")
    sys.exit(1)

for root, dirs, files in os.walk(ADDONS_PATH):
    for file in files:
        if file.endswith(".xml"):
            path = os.path.join(root, file)

            try:
                ET.parse(path)
                print(f"✓ {path}")
            except ET.ParseError as e:
                errors.append((path, str(e)))

if errors:
    print("\n❌ XML errors found:")

    for path, error in errors:
        print(f"\n{path}")
        print(error)

    sys.exit(1)

print("\n✅ All XML files are valid.")
