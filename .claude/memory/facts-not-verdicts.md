---
name: facts-not-verdicts
description: Sightglass reports ranked facts with evidence, never "malicious" or "safe" verdicts
metadata:
  type: project
---

Every signal is a fact with evidence attached (a file, a line, an attestation field) and a level: high, check, note or clean. The tool never labels a package malicious or safe; a reviewer decides.

**Why:** False positives are expected (legitimate telemetry, build-generated files). Verdicts that turn out wrong train people to ignore the page; evidence lets them decide quickly.
**How to apply:** Word signal messages as observations ("is in the wheel but not in the git tag"), not judgments. A failed source match is "couldn't compare", never a high signal by itself. See [[not-a-scanner]].
