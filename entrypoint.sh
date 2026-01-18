#!/bin/bash
# Entrypoint script for the Lumina Capital container

set -e

# Check if running as Lambda
if [ -n "$AWS_LAMBDA_RUNTIME_API" ]; then
    # Running in Lambda - use the runtime interface client
    exec python -m awslambdaric src.adapters.lambda_handler.handler
else
    # Running locally - use the main CLI
    exec python -m src.main "$@"
fi
