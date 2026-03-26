#!/usr/bin/env python
import os
import sys

# Éviter l'initialisation DB pendant le build
os.environ['BUILDING_DOCKER'] = 'true'

from app import create_app

print("🔨 Building assets...")

app = create_app()

os.makedirs('static/dist/css', exist_ok=True)
os.makedirs('static/dist/js', exist_ok=True)

with app.app_context():
    assets_env = app.jinja_env.assets_environment
    
    for bundle_name, bundle in assets_env._named_bundles.items():
        print(f"  Building {bundle_name}...")
        bundle.build(force=True)
        print(f"    ✅ {bundle_name}")

print("✅ All assets built successfully!")