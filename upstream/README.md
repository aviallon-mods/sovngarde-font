# Upstream fonts (vendored, unmodified)

The build reads these files and writes new ones next to them; it never edits
them. They are committed so a build is reproducible from this repository alone
(the Nexus files are behind a login and get replaced when the mod updates).

## Where they come from

Nexus mod **386**, *Sovngarde - Mist's Font Replacer*, version **8.9**:

| download | sha256 |
| --- | --- |
| `Sovngarde - Mist's Font Replacer Bold V8.9-386-8-9-1576107205.7z` | `dbbd3a62df88d56178eae25081177129f5089161a1976f28d59b3b82da5e8f03` |
| `Sovngarde Desktop Edition-386-8-9-1761283820.zip` | `80a57d0b935fe1e0316953d8d64ead6b4660551bbaa4fdf48aa3d080220ee32c` |

Extraction, as performed to produce this directory:

```sh
7z x 'Sovngarde - Mist's Font Replacer Bold V8.9-386-8-9-1576107205.7z' -o mod
unzip 'Sovngarde Desktop Edition-386-8-9-1761283820.zip' -d desktop
```

`upstream/` then holds `mod/Data/Interface/*` verbatim and `desktop/Sovngarde*`
with the FontForge sources dropped (`*.sfd`, ~1.5 MB, not read by the build; the
`.gitignore` in this directory makes the intent explicit).

## Licence

SIL Open Font License 1.1 — copyright © 2016 mjorka (mjorka.net), *without
Reserved Font Name*, so modification and redistribution (including under the
same name) are permitted. The full text is `desktop/Sovngarde OFL License.txt`,
also copied to the repository root as `LICENSE-OFL.txt`.