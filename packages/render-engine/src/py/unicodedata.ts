// ``unicodedata.east_asian_width`` (MIGRATION_PLAN.md §4) — the only
// ``unicodedata`` function the render engine uses.
//
// The table is CPython 3.11's Unicode database (unidata_version 14.0.0),
// generated from Python so results are identical for every code point:
//
//   for cp in range(0x110000): unicodedata.east_asian_width(chr(cp))
//
// Encoding: space-separated ranges ``<start hex>[-<end hex>]<code>`` for every
// code point whose width is not ``N``; code ``A``/``F``/``H``/``W`` as in
// Python and ``n`` for ``Na``. Hex digits are lowercase, so the trailing
// uppercase/``n`` code is unambiguous.

import { PyTypeError } from './errors.ts';

export const UNIDATA_VERSION = '14.0.0';

const TABLE = [
  '20-7en a1A a2-a3n a4A a5-a6n a7-a8A aaA acn ad-aeA afn b0-b4A b6-baA bc-bfA c6A d0A d7-d8A de-e1A e6A e8-eaA ',
  'ec-edA f0A f2-f3A f7-faA fcA feA 101A 111A 113A 11bA 126-127A 12bA 131-133A 138A 13f-142A 144A 148-14bA 14dA ',
  '152-153A 166-167A 16bA 1ceA 1d0A 1d2A 1d4A 1d6A 1d8A 1daA 1dcA 251A 261A 2c4A 2c7A 2c9-2cbA 2cdA 2d0A 2d8-2dbA ',
  '2ddA 2dfA 300-36fA 378-379F 380-383F 38bF 38dF 391-3a1A 3a2F 3a3-3a9A 3b1-3c1A 3c3-3c9A 401A 410-44fA 451A ',
  '530F 557-558F 58b-58cF 590F 5c8-5cfF 5eb-5eeF 5f5-5ffF 70eF 74b-74cF 7b2-7bfF 7fb-7fcF 82e-82fF 83fF 85c-85dF ',
  '85fF 86b-86fF 88fF 892-897F 984F 98d-98eF 991-992F 9a9F 9b1F 9b3-9b5F 9ba-9bbF 9c5-9c6F 9c9-9caF 9cf-9d6F ',
  '9d8-9dbF 9deF 9e4-9e5F 9ff-a00F a04F a0b-a0eF a11-a12F a29F a31F a34F a37F a3a-a3bF a3dF a43-a46F a49-a4aF ',
  'a4e-a50F a52-a58F a5dF a5f-a65F a77-a80F a84F a8eF a92F aa9F ab1F ab4F aba-abbF ac6F acaF ace-acfF ad1-adfF ',
  'ae4-ae5F af2-af8F b00F b04F b0d-b0eF b11-b12F b29F b31F b34F b3a-b3bF b45-b46F b49-b4aF b4e-b54F b58-b5bF b5eF ',
  'b64-b65F b78-b81F b84F b8b-b8dF b91F b96-b98F b9bF b9dF ba0-ba2F ba5-ba7F bab-badF bba-bbdF bc3-bc5F bc9F ',
  'bce-bcfF bd1-bd6F bd8-be5F bfb-bffF c0dF c11F c29F c3a-c3bF c45F c49F c4e-c54F c57F c5b-c5cF c5e-c5fF c64-c65F ',
  'c70-c76F c8dF c91F ca9F cb4F cba-cbbF cc5F cc9F cce-cd4F cd7-cdcF cdfF ce4-ce5F cf0F cf3-cffF d0dF d11F d45F ',
  'd49F d50-d53F d64-d65F d80F d84F d97-d99F db2F dbcF dbe-dbfF dc7-dc9F dcb-dceF dd5F dd7F de0-de5F df0-df1F ',
  'df5-e00F e3b-e3eF e5c-e80F e83F e85F e8bF ea4F ea6F ebe-ebfF ec5F ec7F ece-ecfF eda-edbF ee0-effF f48F ',
  'f6d-f70F f98F fbdF fcdF fdb-fffF 10c6F 10c8-10ccF 10ce-10cfF 1100-115fW 1249F 124e-124fF 1257F 1259F ',
  '125e-125fF 1289F 128e-128fF 12b1F 12b6-12b7F 12bfF 12c1F 12c6-12c7F 12d7F 1311F 1316-1317F 135b-135cF ',
  '137d-137fF 139a-139fF 13f6-13f7F 13fe-13ffF 169d-169fF 16f9-16ffF 1716-171eF 1737-173fF 1754-175fF 176dF 1771F ',
  '1774-177fF 17de-17dfF 17ea-17efF 17fa-17ffF 181a-181fF 1879-187fF 18ab-18afF 18f6-18ffF 191fF 192c-192fF ',
  '193c-193fF 1941-1943F 196e-196fF 1975-197fF 19ac-19afF 19ca-19cfF 19db-19ddF 1a1c-1a1dF 1a5fF 1a7d-1a7eF ',
  '1a8a-1a8fF 1a9a-1a9fF 1aae-1aafF 1acf-1affF 1b4d-1b4fF 1b7fF 1bf4-1bfbF 1c38-1c3aF 1c4a-1c4cF 1c89-1c8fF ',
  '1cbb-1cbcF 1cc8-1ccfF 1cfb-1cffF 1f16-1f17F 1f1e-1f1fF 1f46-1f47F 1f4e-1f4fF 1f58F 1f5aF 1f5cF 1f5eF ',
  '1f7e-1f7fF 1fb5F 1fc5F 1fd4-1fd5F 1fdcF 1ff0-1ff1F 1ff5F 1fffF 2010A 2013-2016A 2018-2019A 201c-201dA ',
  '2020-2022A 2024-2027A 2030A 2032-2033A 2035A 203bA 203eA 2065F 2072-2073F 2074A 207fA 2081-2084A 208fF ',
  '209d-209fF 20a9H 20acA 20c1-20cfF 20f1-20ffF 2103A 2105A 2109A 2113A 2116A 2121-2122A 2126A 212bA 2153-2154A ',
  '215b-215eA 2160-216bA 2170-2179A 2189A 218c-218fF 2190-2199A 21b8-21b9A 21d2A 21d4A 21e7A 2200A 2202-2203A ',
  '2207-2208A 220bA 220fA 2211A 2215A 221aA 221d-2220A 2223A 2225A 2227-222cA 222eA 2234-2237A 223c-223dA 2248A ',
  '224cA 2252A 2260-2261A 2264-2267A 226a-226bA 226e-226fA 2282-2283A 2286-2287A 2295A 2299A 22a5A 22bfA 2312A ',
  '231a-231bW 2329-232aW 23e9-23ecW 23f0W 23f3W 2427-243fF 244b-245fF 2460-24e9A 24eb-254bA 2550-2573A 2580-258fA ',
  '2592-2595A 25a0-25a1A 25a3-25a9A 25b2-25b3A 25b6-25b7A 25bc-25bdA 25c0-25c1A 25c6-25c8A 25cbA 25ce-25d1A ',
  '25e2-25e5A 25efA 25fd-25feW 2605-2606A 2609A 260e-260fA 2614-2615W 261cA 261eA 2640A 2642A 2648-2653W ',
  '2660-2661A 2663-2665A 2667-266aA 266c-266dA 266fA 267fW 2693W 269e-269fA 26a1W 26aa-26abW 26bd-26beW 26bfA ',
  '26c4-26c5W 26c6-26cdA 26ceW 26cf-26d3A 26d4W 26d5-26e1A 26e3A 26e8-26e9A 26eaW 26eb-26f1A 26f2-26f3W 26f4A ',
  '26f5W 26f6-26f9A 26faW 26fb-26fcA 26fdW 26fe-26ffA 2705W 270a-270bW 2728W 273dA 274cW 274eW 2753-2755W 2757W ',
  '2776-277fA 2795-2797W 27b0W 27bfW 27e6-27edn 2985-2986n 2b1b-2b1cW 2b50W 2b55W 2b56-2b59A 2b74-2b75F 2b96F ',
  '2cf4-2cf8F 2d26F 2d28-2d2cF 2d2e-2d2fF 2d68-2d6eF 2d71-2d7eF 2d97-2d9fF 2da7F 2dafF 2db7F 2dbfF 2dc7F 2dcfF ',
  '2dd7F 2ddfF 2e5e-2e7fF 2e80-2e99W 2e9aF 2e9b-2ef3W 2ef4-2effF 2f00-2fd5W 2fd6-2fefF 2ff0-2ffbW 2ffc-3000F ',
  '3001-303eW 3040F 3041-3096W 3097-3098F 3099-30ffW 3100-3104F 3105-312fW 3130F 3131-318eW 318fF 3190-31e3W ',
  '31e4-31efF 31f0-321eW 321fF 3220-3247W 3248-324fA 3250-4dbfW 4e00-a48cW a48d-a48fF a490-a4c6W a4c7-a4cfF ',
  'a62c-a63fF a6f8-a6ffF a7cb-a7cfF a7d2F a7d4F a7da-a7f1F a82d-a82fF a83a-a83fF a878-a87fF a8c6-a8cdF a8da-a8dfF ',
  'a954-a95eF a960-a97cW a97d-a97fF a9ceF a9da-a9ddF a9ffF aa37-aa3fF aa4e-aa4fF aa5a-aa5bF aac3-aadaF aaf7-ab00F ',
  'ab07-ab08F ab0f-ab10F ab17-ab1fF ab27F ab2fF ab6c-ab6fF abee-abefF abfa-abffF ac00-d7a3W d7a4-d7afF d7c7-d7caF ',
  'd7fc-d7ffF e000-f8ffA f900-fa6dW fa6e-fa6fF fa70-fad9W fada-faffF fb07-fb12F fb18-fb1cF fb37F fb3dF fb3fF ',
  'fb42F fb45F fbc3-fbd2F fd90-fd91F fdc8-fdceF fdd0-fdefF fe00-fe0fA fe10-fe19W fe1a-fe1fF fe30-fe52W fe53F ',
  'fe54-fe66W fe67F fe68-fe6bW fe6c-fe6fF fe75F fefd-fefeF ff00-ff60F ff61-ffbeH ffbf-ffc1F ffc2-ffc7H ffc8-ffc9F ',
  'ffca-ffcfH ffd0-ffd1F ffd2-ffd7H ffd8-ffd9F ffda-ffdcH ffdd-ffe7F ffe8-ffeeH ffef-fff8F fffdA fffe-ffffF ',
  '1000cF 10027F 1003bF 1003eF 1004e-1004fF 1005e-1007fF 100fb-100ffF 10103-10106F 10134-10136F 1018fF ',
  '1019d-1019fF 101a1-101cfF 101fe-1027fF 1029d-1029fF 102d1-102dfF 102fc-102ffF 10324-1032cF 1034b-1034fF ',
  '1037b-1037fF 1039eF 103c4-103c7F 103d6-103ffF 1049e-1049fF 104aa-104afF 104d4-104d7F 104fc-104ffF 10528-1052fF ',
  '10564-1056eF 1057bF 1058bF 10593F 10596F 105a2F 105b2F 105baF 105bd-105ffF 10737-1073fF 10756-1075fF ',
  '10768-1077fF 10786F 107b1F 107bb-107ffF 10806-10807F 10809F 10836F 10839-1083bF 1083d-1083eF 10856F ',
  '1089f-108a6F 108b0-108dfF 108f3F 108f6-108faF 1091c-1091eF 1093a-1093eF 10940-1097fF 109b8-109bbF 109d0-109d1F ',
  '10a04F 10a07-10a0bF 10a14F 10a18F 10a36-10a37F 10a3b-10a3eF 10a49-10a4fF 10a59-10a5fF 10aa0-10abfF ',
  '10ae7-10aeaF 10af7-10affF 10b36-10b38F 10b56-10b57F 10b73-10b77F 10b92-10b98F 10b9d-10ba8F 10bb0-10bffF ',
  '10c49-10c7fF 10cb3-10cbfF 10cf3-10cf9F 10d28-10d2fF 10d3a-10e5fF 10e7fF 10eaaF 10eae-10eafF 10eb2-10effF ',
  '10f28-10f2fF 10f5a-10f6fF 10f8a-10fafF 10fcc-10fdfF 10ff7-10fffF 1104e-11051F 11076-1107eF 110c3-110ccF ',
  '110ce-110cfF 110e9-110efF 110fa-110ffF 11135F 11148-1114fF 11177-1117fF 111e0F 111f5-111ffF 11212F ',
  '1123f-1127fF 11287F 11289F 1128eF 1129eF 112aa-112afF 112eb-112efF 112fa-112ffF 11304F 1130d-1130eF ',
  '11311-11312F 11329F 11331F 11334F 1133aF 11345-11346F 11349-1134aF 1134e-1134fF 11351-11356F 11358-1135cF ',
  '11364-11365F 1136d-1136fF 11375-113ffF 1145cF 11462-1147fF 114c8-114cfF 114da-1157fF 115b6-115b7F 115de-115ffF ',
  '11645-1164fF 1165a-1165fF 1166d-1167fF 116ba-116bfF 116ca-116ffF 1171b-1171cF 1172c-1172fF 11747-117ffF ',
  '1183c-1189fF 118f3-118feF 11907-11908F 1190a-1190bF 11914F 11917F 11936F 11939-1193aF 11947-1194fF ',
  '1195a-1199fF 119a8-119a9F 119d8-119d9F 119e5-119ffF 11a48-11a4fF 11aa3-11aafF 11af9-11bffF 11c09F 11c37F ',
  '11c46-11c4fF 11c6d-11c6fF 11c90-11c91F 11ca8F 11cb7-11cffF 11d07F 11d0aF 11d37-11d39F 11d3bF 11d3eF ',
  '11d48-11d4fF 11d5a-11d5fF 11d66F 11d69F 11d8fF 11d92F 11d99-11d9fF 11daa-11edfF 11ef9-11fafF 11fb1-11fbfF ',
  '11ff2-11ffeF 1239a-123ffF 1246fF 12475-1247fF 12544-12f8fF 12ff3-12fffF 1342fF 13439-143ffF 14647-167ffF ',
  '16a39-16a3fF 16a5fF 16a6a-16a6dF 16abfF 16aca-16acfF 16aee-16aefF 16af6-16affF 16b46-16b4fF 16b5aF 16b62F ',
  '16b78-16b7cF 16b90-16e3fF 16e9b-16effF 16f4b-16f4eF 16f88-16f8eF 16fa0-16fdfF 16fe0-16fe4W 16fe5-16fefF ',
  '16ff0-16ff1W 16ff2-16fffF 17000-187f7W 187f8-187ffF 18800-18cd5W 18cd6-18cffF 18d00-18d08W 18d09-1afefF ',
  '1aff0-1aff3W 1aff4F 1aff5-1affbW 1affcF 1affd-1affeW 1afffF 1b000-1b122W 1b123-1b14fF 1b150-1b152W ',
  '1b153-1b163F 1b164-1b167W 1b168-1b16fF 1b170-1b2fbW 1b2fc-1bbffF 1bc6b-1bc6fF 1bc7d-1bc7fF 1bc89-1bc8fF ',
  '1bc9a-1bc9bF 1bca4-1ceffF 1cf2e-1cf2fF 1cf47-1cf4fF 1cfc4-1cfffF 1d0f6-1d0ffF 1d127-1d128F 1d1eb-1d1ffF ',
  '1d246-1d2dfF 1d2f4-1d2ffF 1d357-1d35fF 1d379-1d3ffF 1d455F 1d49dF 1d4a0-1d4a1F 1d4a3-1d4a4F 1d4a7-1d4a8F ',
  '1d4adF 1d4baF 1d4bcF 1d4c4F 1d506F 1d50b-1d50cF 1d515F 1d51dF 1d53aF 1d53fF 1d545F 1d547-1d549F 1d551F ',
  '1d6a6-1d6a7F 1d7cc-1d7cdF 1da8c-1da9aF 1daa0F 1dab0-1deffF 1df1f-1dfffF 1e007F 1e019-1e01aF 1e022F 1e025F ',
  '1e02b-1e0ffF 1e12d-1e12fF 1e13e-1e13fF 1e14a-1e14dF 1e150-1e28fF 1e2af-1e2bfF 1e2fa-1e2feF 1e300-1e7dfF 1e7e7F ',
  '1e7ecF 1e7efF 1e7ffF 1e8c5-1e8c6F 1e8d7-1e8ffF 1e94c-1e94fF 1e95a-1e95dF 1e960-1ec70F 1ecb5-1ed00F ',
  '1ed3e-1edffF 1ee04F 1ee20F 1ee23F 1ee25-1ee26F 1ee28F 1ee33F 1ee38F 1ee3aF 1ee3c-1ee41F 1ee43-1ee46F 1ee48F ',
  '1ee4aF 1ee4cF 1ee50F 1ee53F 1ee55-1ee56F 1ee58F 1ee5aF 1ee5cF 1ee5eF 1ee60F 1ee63F 1ee65-1ee66F 1ee6bF 1ee73F ',
  '1ee78F 1ee7dF 1ee7fF 1ee8aF 1ee9c-1eea0F 1eea4F 1eeaaF 1eebc-1eeefF 1eef2-1efffF 1f004W 1f02c-1f02fF ',
  '1f094-1f09fF 1f0af-1f0b0F 1f0c0F 1f0cfW 1f0d0F 1f0f6-1f0ffF 1f100-1f10aA 1f110-1f12dA 1f130-1f169A ',
  '1f170-1f18dA 1f18eW 1f18f-1f190A 1f191-1f19aW 1f19b-1f1acA 1f1ae-1f1e5F 1f200-1f202W 1f203-1f20fF 1f210-1f23bW ',
  '1f23c-1f23fF 1f240-1f248W 1f249-1f24fF 1f250-1f251W 1f252-1f25fF 1f260-1f265W 1f266-1f2ffF 1f300-1f320W ',
  '1f32d-1f335W 1f337-1f37cW 1f37e-1f393W 1f3a0-1f3caW 1f3cf-1f3d3W 1f3e0-1f3f0W 1f3f4W 1f3f8-1f43eW 1f440W ',
  '1f442-1f4fcW 1f4ff-1f53dW 1f54b-1f54eW 1f550-1f567W 1f57aW 1f595-1f596W 1f5a4W 1f5fb-1f64fW 1f680-1f6c5W ',
  '1f6ccW 1f6d0-1f6d2W 1f6d5-1f6d7W 1f6d8-1f6dcF 1f6dd-1f6dfW 1f6eb-1f6ecW 1f6ed-1f6efF 1f6f4-1f6fcW 1f6fd-1f6ffF ',
  '1f774-1f77fF 1f7d9-1f7dfF 1f7e0-1f7ebW 1f7ec-1f7efF 1f7f0W 1f7f1-1f7ffF 1f80c-1f80fF 1f848-1f84fF 1f85a-1f85fF ',
  '1f888-1f88fF 1f8ae-1f8afF 1f8b2-1f8ffF 1f90c-1f93aW 1f93c-1f945W 1f947-1f9ffW 1fa54-1fa5fF 1fa6e-1fa6fF ',
  '1fa70-1fa74W 1fa75-1fa77F 1fa78-1fa7cW 1fa7d-1fa7fF 1fa80-1fa86W 1fa87-1fa8fF 1fa90-1faacW 1faad-1faafF ',
  '1fab0-1fabaW 1fabb-1fabfF 1fac0-1fac5W 1fac6-1facfF 1fad0-1fad9W 1fada-1fadfF 1fae0-1fae7W 1fae8-1faefF ',
  '1faf0-1faf6W 1faf7-1faffF 1fb93F 1fbcb-1fbefF 1fbfa-1ffffF 20000-2a6dfW 2a6e0-2a6ffF 2a700-2b738W 2b739-2b73fF ',
  '2b740-2b81dW 2b81e-2b81fF 2b820-2cea1W 2cea2-2ceafF 2ceb0-2ebe0W 2ebe1-2f7ffF 2f800-2fa1dW 2fa1e-2ffffF ',
  '30000-3134aW 3134b-e0000F e0002-e001fF e0080-e00ffF e0100-e01efA e01f0-effffF f0000-ffffdA ffffe-fffffF ',
  '100000-10fffdA 10fffe-10ffffF ',
].join('');

const CODES: Record<string, string> = { A: 'A', F: 'F', H: 'H', n: 'Na', W: 'W' };

let starts: number[] | undefined;
let ends: number[] | undefined;
let widths: string[] | undefined;

function load(): void {
  starts = [];
  ends = [];
  widths = [];
  for (const token of TABLE.split(' ')) {
    if (!token) continue;
    const code = token[token.length - 1];
    const [start, end] = token.slice(0, -1).split('-');
    const first = parseInt(start, 16);
    starts.push(first);
    ends.push(end === undefined ? first : parseInt(end, 16));
    widths.push(CODES[code]);
  }
}

/** ``unicodedata.east_asian_width(ch)`` -> ``'F' | 'H' | 'W' | 'Na' | 'A' | 'N'``. */
export function east_asian_width(ch: string): string {
  const code = ch.codePointAt(0);
  if (code === undefined || ch.length !== (code > 0xffff ? 2 : 1)) {
    throw new PyTypeError('east_asian_width() argument must be a unicode character');
  }
  if (!starts) load();
  let lo = 0;
  let hi = starts!.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (code < starts![mid]) hi = mid - 1;
    else if (code > ends![mid]) lo = mid + 1;
    else return widths![mid];
  }
  return 'N';
}
