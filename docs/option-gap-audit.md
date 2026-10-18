# CLI option gap audit

The starting catalogue has 584/624 option-effect mappings, plus 40 options
accounted for only by equivalence checks. This is an implementation audit, not
passing execution evidence. Existing equivalence cases remain useful and are
not removed when effect cases are added.

## All 40 remaining options

| Options | Count | Decision |
| --- | ---: | --- |
| `--verbose` and `--ostree-verbose` on `permissions`, `permission-show`, `permission-set`, `permission-remove`, `permission-reset`, `document-export`, `documents`, `document-info`, `document-unexport`, `ps`, `enter`, `kill`, `history` | 26 | Retain equivalence. Prioritize actual permission, process, and history outcomes over requiring extra diagnostic lines. A quiet success path is not evidence that these flags are broken. |
| `--verbose` on `info`, `repo`, `build-init`, `build-bundle`, `build-sign`; `--ostree-verbose` on `build-finish` | 6 | Retain equivalence. Other diagnostic flags already have controlled effect checks. Do not manufacture work or depend on exact implementation-specific log text merely to raise reach. |
| `build --allow`, `build --disallow` | 2 | Retain the actual ptrace equivalence check. The tested developer permission is implicit for build sandboxes; this does not establish a distinct restriction effect. Investigate other documented features separately before granting effect credit. |
| `document-export --allow-read` | 1 | Retain equivalence. Read allowance is already the default; regranting after revocation alone would not distinguish this flag from omission. |
| `preinstall --system` | 1 | Retain equivalence. System is this command's default; existing competing-store checks establish selection without claiming an omission contrast. |
| `build-bundle --gpg-homedir` | 1 | Retain equivalence. In the catalogue reference source this option is declared but not consumed. Do not infer a signing effect merely from its help text. Revisit if an implementation gives it a documented effect. |
| `build-update-repo --static-delta-jobs` | 1 | Defer. Meaningful coverage requires showing a worker budget with actual delta generation. Successful output with `--static-delta-jobs=1` is insufficient, and wall-clock timing is a fragile concurrency oracle. |
| `remote-add --signature-lookaside`, `remote-modify --signature-lookaside` | 2 | Highest priority: security-relevant retrieval and verification paths, with observable requests, independently signed inputs, rejection controls, and executable expected payloads. |

## Selected five effect cases

All use independent OCI app revisions and disposable signing material prepared
by reference tooling. The target never produces the signatures used as its
verification oracle. A native installed runtime isolates app signature failures
from dependency installation order.

1. **Missing signature:** configured URL returns 404; installation must fail
   without changing deployments. Publishing the trusted signature at that same
   URL must permit execution of A.
2. **Untrusted signer:** a second disposable key signs the correct image, but is
   not imported into the remote. Reject it, then accept a trusted replacement.
3. **Damaged signature:** truncate the signed payload without changing the image
   or trusted key. Reject it, then accept the original signature.
4. **Modified URL:** begin with a missing-signature URL, then change only the
   remote's lookaside URL. Fetch the replacement URL, not the old one, and run A.
5. **Stale update signature:** install signed A, publish B, and serve A's valid
   signature at B's signature path. Reject B and retain runnable A; accept B only
   after its correctly bound signature replaces the stale one.

These cases add effect mappings for **two options**, not five. The resulting
implemented option reach is 586/624 (93.91%), leaving 38 equivalence-only options.
They intentionally do not change requirement denominators. All five are hard
failures under the runner's expected-failure policy.

The next non-diagnostic candidate is actual delta-worker budgeting, once a
portable observation strategy is available. Reaching 100% should not require
claiming effects for default-equivalent or inert options.
