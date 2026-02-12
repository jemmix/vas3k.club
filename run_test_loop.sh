#!/bin/bash
# Run telegram tests in a loop to check for flakiness

RUNS=10
FAILED=0

mkdir -p test_outputs

for i in $(seq 1 $RUNS); do
    echo "========================================"
    echo "Run $i of $RUNS"
    echo "========================================"

    pipenv run python manage.py test --tag telegram --verbosity=1 \
        > test_outputs/run_${i}_stdout.txt \
        2> test_outputs/run_${i}_stderr.txt

    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo "FAILED on run $i (exit code: $EXIT_CODE)"
        FAILED=1
        break
    else
        echo "PASSED run $i"
    fi
done

if [ $FAILED -eq 0 ]; then
    echo "All $RUNS runs passed successfully!"
    exit 0
else
    echo "Test suite failed on run $i"
    exit 1
fi
