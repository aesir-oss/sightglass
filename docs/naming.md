# Naming

Decided 2026-10-16: **Sightglass**, repository `aesir-oss/sightglass`.

A sight glass is the window in a pipe or tank that shows what's actually flowing through it.

## Why the registry clashes don't matter

The plain name `sightglass` is taken by unrelated projects:

| Where | Project |
|---|---|
| PyPI | `sightglass`: live dashboards for a running program (active in 2026) |
| npm | `sightglass`: an observable keypath engine (last updated 2022) |
| crates.io | `sightglass`: Wasmtime and Cranelift benchmark tooling (bytecodealliance/sightglass) |
| GitHub | An organization named `sightglass` |

Sightglass is a hosted web service and a GitHub App, so it doesn't need those names. What it does need, checked on
2026-10-16:

| Name | Status |
|---|---|
| GitHub App slug `sightglass` | `github.com/apps/sightglass` returned 404, so no public app uses it |
| Repository `aesir-oss/sightglass` | Created |
| Container images | Namespaced (`ghcr.io/aesir-oss/sightglass`), no clash |
| `sightglass.dev`, `sightglass.app` | Registered by others |
| `sightglass.io` | Listed for sale |
| `sightglass.sh`, `getsightglass.dev` | No DNS records found; probably unregistered |

None of the existing projects is in supply chain security. If a CLI is ever published to PyPI or crates.io, it needs a
qualified name such as `sightglass-cli`. Avoid one-character variants such as `sightglas` or `sight-glass`: they'd look
like typosquats, and PyPI is likely to reject names that differ from an existing one only by separators.

## Names considered

Availability is as of 2026-10-16 across PyPI, npm, crates.io and conda-forge.

| Theme | Names | Notes |
|---|---|---|
| Shipping and inspection | Lading, Customs, Assay, Shipped, Waybill, Tally, Weighbridge, Docket | Not pursued |
| Instruments | Loupe, Sightglass, Touchstone, Borescope, Candler, Lightbox, Peephole | Borescope taken; Candler free everywhere |
| Indicators | Telltale, Witness, Evident, Hallmark, Plumb | Telltale taken; `telltale-diff` free |
| Norse | Skyggn (second sight), Vakr (watchful), Skuggsjá (mirror), Vitni (witness), Skoðun (inspection), Merki (sign), Varðberg (lookout), Gætir (keeper), Glitnir | All free everywhere; none chosen |
| Norse, close to English | Heill (whole), Sannr (true), Rannsak (to search), Gaum (heed), Kenning, Hrein (clean) | Free everywhere; Traust (trust) is used by an active security project |
| Norse plus English | Heimsight, Odinsight, Runeglass, Ravenglass, Ravenscope, Runesight, Spaewife, Spaeglass | Free everywhere |
| Sightglass variants | Siktglass (Norwegian), Siktglas (Swedish), Skueglas (Danish), Sightgauge, Sightlens, Peekglass | Free everywhere |
| Other myths | Lynkeus, Rashnu, Udjat, Xiezhi, Shamash | Rashnu and Udjat free everywhere |
| Taken or crowded | Heimdall, Mímir, Huginn, Muninn, Forseti, Kvasir, Janus, Argus, Panoptes, Ma'at, Aletheia, Sleuth, Sightline | Avoid |
