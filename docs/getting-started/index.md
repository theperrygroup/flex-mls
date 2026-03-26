# Getting Started

The library is organized around a single `FlexMlsClient` facade that lazily
exposes resource-specific clients such as `properties`, `members`, and
`lookup`.

Choose an authentication strategy first:

- bearer access token for single-user or generic-agent integrations
- OpenID Connect when Flexmls users must sign in and authorize access
