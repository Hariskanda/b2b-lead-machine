#!/usr/bin/env bash
set -e

echo "=================================================="
echo "🚀 Pushing B2B Lead Machine to GitHub"
echo "Repository: https://github.com/Hariskanda/b2b-lead-machine.git"
echo "=================================================="

# Ensure branch is main
git branch -M main

# Push to GitHub
echo "Pushing code to main branch..."
git push -u origin main

echo ""
echo "✅ Push complete! You can now deploy on Streamlit Community Cloud."
