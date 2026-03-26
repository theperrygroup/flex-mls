# Authentication

Spark RESO requests use `Authorization: Bearer ...`.

`flex_mls` supports two auth modes:

- direct bearer tokens for Spark personal access token workflows
- OpenID Connect helpers for authorization-code, refresh, and revoke flows

See the API reference for `flex_mls.auth` and `flex_mls.client.FlexMlsClient`
for concrete usage examples.
