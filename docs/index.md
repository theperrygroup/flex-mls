# flex_mls

`flex_mls` is a typed Python client for the Spark RESO Web API used by
Flexmls. It supports both direct bearer-token authentication and Spark's
OpenID Connect authorization-code flow.

Use the guides in this documentation to:

- configure bearer-token and OIDC authentication
- query RESO resources with standard OData parameters
- expand related property resources such as media and open houses
- build replication workflows that follow Spark's paging and timestamp rules
