// Upload each collected binary as its OWN GitHub Actions artifact so a
// downstream job can download exactly the binary it needs
// (actions/download-artifact with name: <prefix><binary>).
//
// Must run as `using: node20` (see action.yml) so the runner injects
// ACTIONS_RUNTIME_TOKEN — a composite `run: node …` step does not reliably
// receive that env on self-hosted runners.

const { readdirSync, statSync } = require("node:fs");
const { join, basename } = require("node:path");
const core = require("@actions/core");
const { DefaultArtifactClient } = require("@actions/artifact");

async function main() {
  const dir = core.getInput("directory", { required: true });
  const prefix = core.getInput("prefix") || "bin-";
  const retentionDays = Number(core.getInput("retention-days") || "7");

  let files = [];
  try {
    files = readdirSync(dir)
      .map((f) => join(dir, f))
      .filter((p) => statSync(p).isFile())
      .filter((p) => basename(p) !== "manifest.txt");
  } catch {
    core.info(`No directory at ${dir} — nothing to upload`);
    return;
  }

  if (files.length === 0) {
    core.info(`No files in ${dir} — nothing to upload`);
    return;
  }

  const client = new DefaultArtifactClient();
  let uploaded = 0;
  for (const file of files) {
    const name = `${prefix}${basename(file)}`;
    // Re-run attempts collide with the previous attempt's artifact of the same
    // name (v4 artifacts are immutable per run) — delete-then-upload.
    try {
      await client.deleteArtifact(name);
      core.info(`replaced existing artifact ${name}`);
    } catch {
      /* no existing artifact — fine */
    }
    const { id, size } = await client.uploadArtifact(name, [file], dir, {
      retentionDays,
      compressionLevel: 6,
    });
    core.info(`uploaded ${name} (id=${id}, ${size} bytes)`);
    uploaded += 1;
  }
  core.info(`uploaded ${uploaded} per-binary artifact(s) from ${dir}`);
}

main().catch((err) => {
  core.setFailed(err instanceof Error ? err.message : String(err));
});
