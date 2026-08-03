#!/usr/bin/env bash
# Quick setup script for job-analytics-dashboard

set -euo pipefail

ENV_NAME="job-analytics"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Setting up Job Analytics Dashboard..."

if ! command -v conda >/dev/null 2>&1; then
    echo "Error: conda is not installed or not on PATH."
    echo "Install Miniconda/Anaconda first, then rerun this script."
    exit 1
fi

echo "Preparing conda environment '$ENV_NAME'..."
if conda env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"; then
    conda env update -f environment.yml --prune
else
    conda env create -f environment.yml
fi

echo "Activating environment..."
eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"

echo "Creating data directories..."
mkdir -p data/raw data/processed data/features

if [ ! -f "data/raw/SGJobData.csv" ]; then
    echo "SGJobData.csv not found in data/raw/."
    echo "Copy SGJobData.csv to data/raw/ before running the pipeline."
else
    echo "Found data/raw/SGJobData.csv"
fi

echo
echo "Setup complete."
echo
echo "Next steps:"
echo "1. conda activate $ENV_NAME"
echo "2. cp /path/to/SGJobData.csv data/raw/"
echo "3. python -m src.pipeline.pipeline"
echo "4. streamlit run src/dashboard/app.py"
echo
