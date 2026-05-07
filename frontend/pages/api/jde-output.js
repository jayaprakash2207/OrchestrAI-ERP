import fs from "fs";
import path from "path";

function getCandidateStateRoots() {
  return [
    path.resolve(process.cwd(), "..", "data", "state", "autoerp_output"),
    path.resolve(process.cwd(), "..", "data", "state", "extracted"),
  ];
}

function normalizeGenerationId(dirName) {
  return dirName.replace(/^autoerp-/, "");
}

function latestExtractedDir() {
  const candidates = [];
  const roots = getCandidateStateRoots();

  roots.forEach((stateRoot) => {
    if (!fs.existsSync(stateRoot)) {
      return;
    }

    fs.readdirSync(stateRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .forEach((entry) => {
        const full = path.join(stateRoot, entry.name);
        const stat = fs.statSync(full);

        // A valid output dir must contain generated ERP artifacts.
        const hasSchema = fs.existsSync(path.join(full, "schema.json"));
        const hasMaster = fs.existsSync(path.join(full, "master_data.json"));
        if (!hasSchema && !hasMaster) {
          return;
        }

        candidates.push({
          name: entry.name,
          generationId: normalizeGenerationId(entry.name),
          full,
          mtimeMs: stat.mtimeMs,
          root: stateRoot,
        });
      });
  });

  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return candidates.length ? candidates[0] : null;
}

function safeReadJson(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

export default function handler(req, res) {
  try {
    const latest = latestExtractedDir();
    if (!latest) {
      res.status(404).json({ message: "No extracted ERP output found. Generate ERP first." });
      return;
    }

    const generationId = latest.generationId;
    const schema = safeReadJson(path.join(latest.full, "schema.json"));
    const masterData = safeReadJson(path.join(latest.full, "master_data.json"));

    res.status(200).json({
      generationId,
      extractedDir: latest.full,
      sourceRoot: latest.root,
      schema,
      masterData,
      files: fs.readdirSync(latest.full),
    });
  } catch (error) {
    res.status(500).json({ message: "Failed to load ERP output", details: String(error) });
  }
}
