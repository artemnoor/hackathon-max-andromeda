# DATA-API validator provenance

The validator and schema in this directory are copied unchanged from the
organizers' [`stasnorman/example-data-api`](https://gitverse.ru/stasnorman/example-data-api)
repository at commit `8504a6d9b39e6f652bce689d96e88538d7541c6b`.

| Local file | Upstream file | SHA-256 |
|---|---|---|
| `validate_data_api.py` | `validate_data_api.py` | `7f7eb394e3ed300ac23ac8390bc5da8eebc4e09c6b43cf6861f8025e013e6379` |
| `DATA-API.schema.json` | `Example/DATA-API.schema.json` | `8db9f30a469ab2117b68a248d44a39558249184c242c92353cce8d33e9164cc2` |
| `UPSTREAM-LICENSE.md` | `licence.md` | `6fabac47fa2777e97d86e683b346efd6a283ace3ee035305dd8d48b7d243b577` |
| `upstream-requirements.txt` | `requirements.txt` | `99515c82e0e65bd9f0a03f4452b4ae40b2370057ef31a558b0b07c180f271866` |

The repository runs the upstream tool with the locked backend development
environment, which already supplies PyYAML and jsonschema. The upstream
requirements file is retained for provenance; DATA-API-only dependencies are
not added to the Andromeda runtime dependency set.

From the repository root:

```powershell
python scripts/andromeda.py data-api
```

The organizer validator checks schema, DATA-API semantics and endpoint/method
existence in the canonical Public API OpenAPI document. It does not make live
HTTP requests. Set an organizer-accessible HTTPS `api.baseUrl` in
`DATA-API.yaml` before a hosted scenario run.
