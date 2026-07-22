import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

test('lookup_use_case package contains every curated knowledge brief', () => {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const packageScript = path.join(
    repoRoot,
    'infra',
    'assets',
    'package-lookup-use-case.sh',
  );
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lookup-use-case-'));

  try {
    expect(fs.existsSync(packageScript)).toBe(true);
    execFileSync('bash', [packageScript, repoRoot, outputDir]);

    expect(fs.existsSync(path.join(outputDir, 'handler.py'))).toBe(true);
    const knowledgeDir = path.join(outputDir, 'knowledge');
    const index = JSON.parse(
      fs.readFileSync(path.join(knowledgeDir, 'index.json'), 'utf8'),
    );
    for (const entry of Object.values(index) as Array<{ file: string }>) {
      expect(fs.existsSync(path.join(knowledgeDir, entry.file))).toBe(true);
    }
  } finally {
    fs.rmSync(outputDir, { recursive: true, force: true });
  }
});
