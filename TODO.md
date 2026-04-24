# TODO

1. Investigate Amnezia PHP Panel traffic reset. `set-traffic-limit` doesn't reset consumed bytes. Need to find a way to reset statistics or add new limit to existing usage during subscription renew/reset.
2. Fix `provider_payload` bloat in Amnezia. We are storing the Base64 QR code in the JSON payload, which can bloat the SQLite database over time. Should probably drop it or generate it on the fly.
