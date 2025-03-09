#!/bin/bash

# Clean up previous runs
rm -rf prd_chroma_db
rm -rf prd_mock_output/*

# Run the parser tests
python prd_test_parser.py --input prd_mock_data --clean --debug 