# Troubleshooting

Common Spark-specific issues to watch for:

- `401` with Spark code `1020`: your OIDC access token has expired and should be
  refreshed.
- `403` with Spark code `1021`: Spark requires the replication endpoint.
- `403` with Spark code `1019`: the key is restricted by IP or `User-Agent`.
- `429`: the key is over the Spark rate limit.

If a key is failing before any request succeeds, double-check that the MLS data
plan, key role, and authentication mode match the intended use case.
