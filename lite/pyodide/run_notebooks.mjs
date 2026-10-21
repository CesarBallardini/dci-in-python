// Run every notebook in lite/contents under Pyodide, in Node, the way the JupyterLite kernel runs it.
//
// `make lite` stages lite/contents (the notebooks, tests/, pytest.ini, uv.lock) and lite/pypi (the banking
// wheel), which is exactly what the site serves. Each notebook gets a fresh interpreter, as each gets its own
// kernel in the browser. The contents are mounted at /drive, the directory a JupyterLite kernel starts in, and
// a stand-in replaces `piplite`, the one kernel module Node lacks: `banking` resolves to the staged wheel and
// every other requirement goes to micropip, as piplite does.
//
// The pyodide version in package.json must equal the one the kernel pins (jupyterlite-pyodide-kernel 0.8.6 ships
// Pyodide 314.0.6). A cell that raises fails the run, and so does a notebook that leaves a non-zero `exit_code`
// behind, which is how notebook 5 reports the test suite.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadPyodide } from 'pyodide';

const lite = join(dirname(fileURLToPath(import.meta.url)), '..');

const PIPLITE = `
import os
import sys
import types

import micropip

_local = {name.split('-')[0]: f'emfs:/wheels/{name}' for name in os.listdir('/wheels') if name.endswith('.whl')}


async def _install(requirements, **kwargs):
    await micropip.install([_local.get(requirement, requirement) for requirement in requirements], **kwargs)


sys.modules['piplite'] = types.ModuleType('piplite')
sys.modules['piplite'].install = _install
os.chdir('/drive')
`;

async function freshKernel() {
  const py = await loadPyodide();
  py.setStdout({ batched: (line) => console.log(line) });
  py.setStderr({ batched: (line) => console.error(line) });
  const copyIn = (host, target) => {
    py.FS.mkdirTree(target);
    for (const name of readdirSync(host)) {
      if (name === '__pycache__') continue;
      const from = join(host, name);
      if (statSync(from).isDirectory()) copyIn(from, `${target}/${name}`);
      else py.FS.writeFile(`${target}/${name}`, readFileSync(from));
    }
  };
  copyIn(join(lite, 'contents'), '/drive');
  copyIn(join(lite, 'pypi'), '/wheels');
  await py.loadPackage('micropip');
  await py.runPythonAsync(PIPLITE);
  return py;
}

let failed = false;
const notebooks = readdirSync(join(lite, 'contents')).filter((name) => name.endsWith('.ipynb')).sort();
for (const name of notebooks) {
  console.log(`\n##### ${name}`);
  const cells = JSON.parse(readFileSync(join(lite, 'contents', name), 'utf8')).cells;
  const py = await freshKernel();
  const namespace = py.globals.get('dict')();
  try {
    for (const cell of cells.filter((c) => c.cell_type === 'code')) {
      const source = Array.isArray(cell.source) ? cell.source.join('') : cell.source;
      await py.runPythonAsync(source, { globals: namespace });
    }
    const exitCode = namespace.get('exit_code');
    if (exitCode !== undefined && Number(exitCode) !== 0) {
      console.error(`${name}: exit_code is ${exitCode}`);
      failed = true;
    }
  } catch (error) {
    console.error(`${name}: ${error}`);
    failed = true;
  }
}
process.exitCode = failed ? 1 : 0;
