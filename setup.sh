#!/bin/bash
# Quick setup script for job-analytics-dashboard

echo "🚀 Setting up Job Analytics Dashboard..."

# Create conda environment
echo "📦 Creating conda environment..."
conda env create -f environment.yml -y

# Activate environment
echo "✅ Activating environment..."
source ~/anaconda3/etc/profile.d/conda.sh || source ~/miniconda3/etc/profile.d/conda.sh
conda activate job-analytics

# Create data directories
echo "📁 Creating data directories..."
mkdir -p data/raw
mkdir -p data/processed

# Check for SGJobData.csv
if [ ! -f "data/raw/SGJobData.csv" ]; then
    echo "⚠️  SGJobData.csv not found in data/raw/"
    echo "   Please copy SGJobData.csv to data/raw/ before running pipeline"
else
    echo "✓ SGJobData.csv found"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Activate environment: conda activate job-analytics"
echo "2. Copy data: cp /path/to/SGJobData.csv data/raw/"
echo "3. Run pipeline: python src/pipeline/pipeline.py"
echo "4. Launch dashboard: streamlit run src/dashboard/app.py"
echo ""
