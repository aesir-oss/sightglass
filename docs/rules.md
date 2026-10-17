# Writing rules

A rule is a pure function from a `PairAnalysis` to zero or more `Signal`s. It reads nothing but its input, does no
I/O, and never runs package code. Rules live in `backend/src/sightglass/rules/` and register on the shared `RULES` set:

```python
from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal


@RULES.rule("timing.recent", version=1, summary="The release was published in the last 7 days")
def recent(analysis: PairAnalysis) -> list[Signal]:
    ...
```

## Ids and versions

- Ids are `group.name` in lowercase, for example `provenance.attestation_dropped`. The group matches the signals table
  in [design.md](design.md#signals). Ids are permanent: stored signals and links refer to them.
- Bump `version` whenever what a rule reports changes: when it fires, its level, its message or its evidence.
  Refactors that don't change any output keep the version.
- A rule that reads versioned data passes `data_version`, such as the date of the top-packages list
  (`pixi run refresh-top-packages`). It is part of the rule-set version, so refreshing the data recomputes analyses.
- The rule-set version (`RULES.version`) is a hash of every id, version and data version. Analyses are stored under it, so a bump,
  a new rule or a removed rule makes stored analyses stale, and they are recomputed.

## Unknown is not a finding

`None` in a `PairAnalysis` means Sightglass couldn't find out: the index was unreachable, the source couldn't be
fetched, the release predates attestations. A rule must not fire on unknown inputs. Every rule has a unit test that
passes `None` for each input it reads and expects no signal.

## Levels

| Level | Use it when |
|---|---|
| high | A reviewer should look before merging: the facts break a pattern the project has kept until now |
| check | Worth a glance, with a common innocent explanation |
| note | Context that helps read the other signals |
| clean | The rule looked and found nothing unusual, when saying so is useful (for example, "attested by the same workflow as 2.4.1") |

## Messages: observations, not judgments

A message says what changed, in plain words, with the specifics. It doesn't say what the change means, guess at
intent, or rate the package. The reviewer decides; the evidence lets them decide quickly.

| Write | Don't write |
|---|---|
| 2.5.0 has no attestation; 2.4.1 was attested by `release.yml` in `kestrel-weather/orbit-client` | 2.5.0 may be compromised |
| `orbit/telemetry.py` is in the wheel but not in tag `v2.5.0` | Suspicious file injected into the wheel |
| New module-level call to `urllib.request.urlopen` in `orbit/__init__.py` | Malicious network beacon on import |
| Published 2 days ago | Too new to be safe |

- Name the file, the versions and the values. Prefer "isn't in" and "differs from" over "missing" and "tampered".
- One fact per signal. Two files that aren't in the tag are two signals, or one signal with two evidence items.
- `Signal` refuses verdict words (malicious, safe, suspicious, compromised and similar) so a message can't slip
  through with one.

## Evidence

Each `Evidence` item points at something a reviewer can open:

- `file`, with `line_start` and `line_end` (1-based, inclusive) and `side` (`old` or `new`) for a line range
- `attestation_field`, such as `publisher.workflow`, for provenance
- `before` and `after` for a value that changed, such as a publisher or a dependency constraint
