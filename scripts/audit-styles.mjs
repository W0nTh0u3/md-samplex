import { readFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const scssFiles = [
  "src/styles/globals.scss",
  "src/styles/_tokens.scss",
  "src/styles/_mixins.scss",
  "src/components/study-app.module.scss",
  "src/components/exam.module.scss",
  "src/components/modal.module.scss",
];
const files = [...scssFiles, "src/styles/tailwind.css"];

const forbidden = [
  [/SpotifyMixUI/i, "Spotify typography"],
  [/color-scheme\s*:\s*dark/i, "dark color scheme"],
  [/--(?:bg|raised|card|text)\s*:/i, "obsolete dark token"],
  [/--green\s*:\s*#1ed760/i, "Spotify green token"],
  [/\.mobile-nav\b/i, "obsolete mobile navigation selector"],
  [/\.feedback-title\b/i, "obsolete feedback title selector"],
];

const contents = await Promise.all(
  files.map(async (file) => [
    file,
    await readFile(path.join(root, file), "utf8"),
  ]),
);
const violations = [];

for (const [file, source] of contents) {
  for (const [pattern, description] of forbidden) {
    if (pattern.test(source)) violations.push(`${file}: ${description}`);
  }
  if (file.endsWith(".scss") && /@import\s+/i.test(source)) {
    violations.push(`${file}: Sass @import rule`);
  }
}

const tailwindStyles = contents.find(
  ([file]) => file === "src/styles/tailwind.css",
)[1];
if (tailwindStyles.trim() !== '@import "tailwindcss";') {
  violations.push(
    "src/styles/tailwind.css: expected the single Tailwind vendor import",
  );
}

const examStyles = contents.find(
  ([file]) => file === "src/components/exam.module.scss",
)[1];
const feedbackBlocks = examStyles.match(/^\s*\.feedback\s*\{/gm) ?? [];
if (feedbackBlocks.length !== 2) {
  violations.push(
    `src/components/exam.module.scss: expected one feedback implementation and one responsive override, found ${feedbackBlocks.length}`,
  );
}
if (!/\.explanation\s*\{[\s\S]*white-space:\s*normal/i.test(examStyles)) {
  violations.push(
    "src/components/exam.module.scss: explanation text must use natural whitespace",
  );
}

if (violations.length) {
  console.error("Style audit failed:");
  for (const violation of violations) console.error(`- ${violation}`);
  process.exitCode = 1;
} else {
  console.log(
    `Style audit passed: ${files.length} style resources, no obsolete dark layer or duplicate feedback implementation.`,
  );
}
