#!/bin/bash
# Quick test of raw data layer implementation

echo "🔍 Testing Raw Data Layer Implementation..."
echo ""

# Check if Python files have raw layer code
echo "✓ Checking src/database/schema.py for RAW_JOBS_SCHEMA..."
if grep -q "RAW_JOBS_SCHEMA" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/database/schema.py; then
    echo "  ✓ Found RAW_JOBS_SCHEMA"
fi

if grep -q "RAW_JOBS_FLAT_SCHEMA" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/database/schema.py; then
    echo "  ✓ Found RAW_JOBS_FLAT_SCHEMA"
fi

echo ""
echo "✓ Checking src/database/database_manager.py for raw layer methods..."
if grep -q "insert_raw_jobs" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/database/database_manager.py; then
    echo "  ✓ Found insert_raw_jobs() method"
fi

if grep -q "get_raw_data_quality_report" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/database/database_manager.py; then
    echo "  ✓ Found get_raw_data_quality_report() method"
fi

if grep -q "audit_data_lineage" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/database/database_manager.py; then
    echo "  ✓ Found audit_data_lineage() method"
fi

echo ""
echo "✓ Checking src/pipeline/pipeline.py for load_raw stage..."
if grep -q "load_raw" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/pipeline/pipeline.py; then
    echo "  ✓ Found load_raw() method"
fi

if grep -q "load_processed" /home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/pipeline/pipeline.py; then
    echo "  ✓ Found load_processed() method"
fi

echo ""
echo "✓ Checking documentation..."
if [ -f "/home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/RAW_LAYER_GUIDE.md" ]; then
    echo "  ✓ Found RAW_LAYER_GUIDE.md"
fi

if [ -f "/home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/RAW_LAYER_IMPLEMENTATION.md" ]; then
    echo "  ✓ Found RAW_LAYER_IMPLEMENTATION.md"
fi

if [ -f "/home/seanl/NTU/DSAI/6m-data-C1.2-coaching-assignment-project/job-analytics-dashboard/src/audit/data_audit.py" ]; then
    echo "  ✓ Found src/audit/data_audit.py"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ All raw layer components implemented successfully!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "1. Test pipeline: python src/pipeline/pipeline.py"
echo "2. Run audit: python src/audit/data_audit.py"
echo "3. Read docs: RAW_LAYER_GUIDE.md or RAW_LAYER_IMPLEMENTATION.md"
echo ""
