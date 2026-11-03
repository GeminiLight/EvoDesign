import { program } from 'commander';
import fs from 'fs';
import {
  computeLayoutPositions,
  parseLayoutRequest,
} from '../src/lib/layout';

program
  .option('-i, --input <path>', 'Input JSON file path')
  .option('-o, --output <path>', 'Output JSON file path')
  .parse(process.argv);

const options = program.opts();

function readInput(): string {
  if (!options.input || options.input === '-') {
    return fs.readFileSync(0, 'utf-8');
  }
  return fs.readFileSync(options.input, 'utf-8');
}

async function run() {
  const input = JSON.parse(readInput());
  const result = computeLayoutPositions(parseLayoutRequest(input));
  const serialized = JSON.stringify(result, null, options.output === '-' ? 0 : 2);

  if (options.output && options.output !== '-') {
    fs.writeFileSync(options.output, serialized);
    return;
  }
  console.log(serialized);
}

run().catch((error: Error) => {
  console.error(error.message);
  process.exitCode = 1;
});
