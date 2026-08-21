# Deployment

The supported release boundary is offline research, shadow mode, and paper mode. A clean checkout may run the small fixture smoke tests without credentials or ignored historical outputs.

The full research command requires rehydrating the verified, ignored market and behavior artifacts described by the manifests. Those large artifacts are intentionally not part of the open-source release bundle.

Live or demo exchange connectivity is not enabled automatically. Any future deployment must pass an independent human review of credentials, limits, monitoring, rollback, and exchange-specific behavior.

