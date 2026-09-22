import { createRequire } from "node:module";
import fs from "node:fs";

const require = createRequire(import.meta.url);
const ts = require(process.argv[2]);
const file = process.argv[3];
const line = Number(process.argv[4]);
const column = Number(process.argv[5]);
const text = fs.readFileSync(file, "utf8");
const options = {
  allowJs: true,
  checkJs: false,
  target: ts.ScriptTarget.Latest,
  module: ts.ModuleKind.ESNext,
};
const host = {
  getScriptFileNames: () => [file],
  getScriptVersion: () => "0",
  getScriptSnapshot: (name) => (name === file ? ts.ScriptSnapshot.fromString(text) : undefined),
  getCurrentDirectory: () => process.cwd(),
  getCompilationSettings: () => options,
  getDefaultLibFileName: (settings) => ts.getDefaultLibFilePath(settings),
  fileExists: ts.sys.fileExists,
  readFile: ts.sys.readFile,
  readDirectory: ts.sys.readDirectory,
  directoryExists: ts.sys.directoryExists,
  getDirectories: ts.sys.getDirectories,
};
const service = ts.createLanguageService(host);
const source = ts.createSourceFile(file, text, options.target, true);
const position = ts.getPositionOfLineAndCharacter(source, line - 1, column - 1);
const info = service.getQuickInfoAtPosition(file, position);
const display = ts.displayPartsToString(info?.displayParts ?? []);
process.stdout.write(JSON.stringify({ display: display || null }));
