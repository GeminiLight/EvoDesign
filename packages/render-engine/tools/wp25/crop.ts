// WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { PNG } from 'pngjs';
import { smart_crop } from '../../src/render_engine/shared/image_cropper.ts';
const D = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/wp25/crop';
const vectors = JSON.parse(readFileSync(D + '/vectors.json', 'utf-8'));
let ok = 0;
for (const v of vectors) {
  const dst = D + '/' + v.name + '_ts_out.jpg';
  let msg = ''; let err: string | null = null;
  try { msg = smart_crop.invoke({ image_path: v.src, output_path: dst, ...v.kw }); } catch (e) { err = (e as Error).constructor.name + ':' + (e as Error).name; }
  const png = dst.replace(/\.jpg$/, '.png');
  let shape = null; let sha = null;
  if (existsSync(png)) {
    const img = PNG.sync.read(readFileSync(png));
    // BGR bytes like cv2.imread
    const bgr = Buffer.alloc(img.width * img.height * 3);
    for (let i = 0, j = 0; j < bgr.length; i += 4, j += 3) { bgr[j] = img.data[i + 2]; bgr[j + 1] = img.data[i + 1]; bgr[j + 2] = img.data[i]; }
    shape = [img.height, img.width, 3]; sha = createHash('sha256').update(bgr).digest('hex');
  }
  const tsMsg = msg.split(D).join('<D>').replace('_ts_out', '_py_out');
  const same = tsMsg === v.msg && JSON.stringify(shape) === JSON.stringify(v.shape ?? null) && sha === (v.sha ?? null) && (!!err === !!v.error);
  if (same) ok++;
  console.log(same ? 'OK  ' : 'DIFF', v.name, v.error ?? '', err ?? '', same ? '' : JSON.stringify({ tsMsg, pyMsg: v.msg, shape, pyShape: v.shape }));
}
console.log(ok + '/' + vectors.length);
