// Upload each collected binary as its OWN GitHub Actions artifact so a
// downstream job can download exactly the binary it needs
// (actions/download-artifact with name: <prefix><binary>) instead of pulling
// the whole build_artifacts tree.
//
// Plain actions/upload-artifact cannot loop (one static step = one artifact),
// so this drives the @actions/artifact toolkit directly.
//
// Usage: node upload-each.mjs <dir> <name-prefix> [retention-days]
//   <dir>           directory whose direct children are uploaded (one artifact each)
//   <name-prefix>   artifact name prefix, e.g. "bin-" -> bin-hauliage_migrator
//   [retention]     artifact retention in days (default 7)
//
// Requires @actions/artifact resolvable from NODE_PATH (the action step
// npm-installs it into $RUNNER_TEMP).

import { readdirSync, statSync } from 'node:fs';
import { join, basename } from 'node:path';

const [dir, prefix = 'bin-', retentionArg] = process.argv.slice(2);
const retentionDays = Number(retentionArg || 7);

if (!dir) {
  console.error('usage: upload-each.mjs <dir> <name-prefix> [retention-days]');
  process.exit(2);
}

const { DefaultArtifactClient } = await import('@actions/artifact');
const client = new DefaultArtifactClient();

let files = [];
try {
  files = readdirSync(dir)
    .map((f) => join(dir, f))
    .filter((p) => statSync(p).isFile())
    // manifest travels with every artifact's sibling metadata, not alone
    .filter((p) => basename(p) !== 'manifest.txt');
} catch {
  console.log(`No directory at ${dir} — nothing to upload`);
  process.exit(0);
}

if (files.length === 0) {
  console.log(`No files in ${dir} — nothing to upload`);
  process.exit(0);
}

let uploaded = 0;
for (const file of files) {
  const name = `${prefix}${basename(file)}`;
  // Re-run attempts collide with the previous attempt's artifact of the same
  // name (v4 artifacts are immutable per run) — delete-then-upload.
  try {
    await client.deleteArtifact(name);
    console.log(`replaced existing artifact ${name}`);
  } catch {
    /* no existing artifact — fine */
  }
  const { id, size } = await client.uploadArtifact(name, [file], dir, {
    retentionDays,
    compressionLevel: 6,
  });
  console.log(`uploaded ${name} (id=${id}, ${size} bytes)`);
  uploaded += 1;
}
console.log(`uploaded ${uploaded} per-binary artifact(s) from ${dir}`);
